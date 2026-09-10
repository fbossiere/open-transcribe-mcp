from pathlib import Path

import pytest

from open_transcribe.domain.audio import (
    ResolvedAudioSource,
    ResolvedTranscribeRequest,
    TimestampMode,
    TranscribeAudioRequest,
    TranscriptStyle,
)
from open_transcribe.domain.capabilities import ModelDescriptor, ModelLifecycle
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.domain.transcript import CanonicalTranscript, CostEstimate
from open_transcribe.providers.base import TranscriptionProvider
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.routing.router import Router, load_routing
from open_transcribe.settings import Settings


def _request(**overrides: object) -> TranscribeAudioRequest:
    data: dict[str, object] = {"source": {"url": "https://example.com/audio.mp3"}}
    data.update(overrides)
    return TranscribeAudioRequest.model_validate(data)


def test_default_routing_selects_microsoft(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    candidates = Router(registry, settings).route(_request())
    assert candidates[0].model.key == "microsoft/MAI-Transcribe-2"


def test_cost_routing_selects_compatible_cheapest(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    candidates = Router(registry, settings).route(
        _request(routing_policy="cost", diarization=False, transcript_style="verbatim")
    )
    assert candidates[0].model.key == "groq/whisper-large-v3-turbo"


def test_strict_capability_rejects_groq_diarization(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    request = _request(
        provider="groq", model="whisper-large-v3", diarization=True, transcript_style="verbatim"
    )
    with pytest.raises(OpenTranscribeError) as caught:
        Router(registry, settings).route(request)
    assert caught.value.response.code == ErrorCode.UNSUPPORTED_CAPABILITY
    assert "diarization" in caught.value.response.details["unsupported"]


def test_non_strict_capability_emits_warning(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    request = _request(
        provider="groq",
        model="whisper-large-v3",
        diarization=True,
        transcript_style="verbatim",
        strict_capabilities=False,
    )
    candidate = Router(registry, settings).route(request)[0]
    assert "requested_capability_not_supported:diarization" in candidate.warnings


def test_no_configured_provider_is_an_error(config_dir: object) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={"auth_mode": "none"},
    )
    registry = ProviderRegistry.from_settings(settings)
    with pytest.raises(OpenTranscribeError) as caught:
        Router(registry, settings).route(_request())
    assert caught.value.response.code == ErrorCode.PROVIDER_UNAVAILABLE


GROQ_LIKE: dict[str, object] = {
    "supports_diarization": False,
    "transcript_styles": {TranscriptStyle.VERBATIM},
}


def descriptor(**overrides: object) -> ModelDescriptor:
    """A fully capable model, so each test restricts exactly one dimension."""
    data: dict[str, object] = {
        "provider": "probe",
        "model": "probe-1",
        "display_name": "Probe 1",
        "lifecycle": ModelLifecycle.GA,
        "languages": "dynamic",
        "supports_url_input": True,
        "supports_diarization": True,
        "timestamp_modes": {TimestampMode.NONE, TimestampMode.SEGMENT, TimestampMode.WORD},
        "transcript_styles": {TranscriptStyle.CLEAN, TranscriptStyle.VERBATIM},
        "supports_language_detection": True,
        "supports_code_switching": True,
        "supports_phrase_hints": True,
        "configured": True,
    }
    data.update(overrides)
    return ModelDescriptor.model_validate(data)


class ProbeProvider(TranscriptionProvider):
    provider_id = "probe"
    configured = True

    def __init__(self, descriptors: list[ModelDescriptor]) -> None:
        self.descriptors = descriptors

    def list_models(self) -> list[ModelDescriptor]:
        return self.descriptors

    async def transcribe(
        self,
        request: ResolvedTranscribeRequest,
        source: ResolvedAudioSource,
        model: ModelDescriptor,
    ) -> CanonicalTranscript:
        raise NotImplementedError

    def estimate_cost(self, model: str, duration_seconds: float) -> CostEstimate:
        raise NotImplementedError


def probe_router(settings: Settings, **overrides: object) -> Router:
    registry = ProviderRegistry([ProbeProvider([descriptor(**overrides)])])
    return Router(registry, settings, routing_config={})


@pytest.mark.parametrize(
    ("capability", "request_overrides", "unsatisfied"),
    [
        ({"lifecycle": ModelLifecycle.PREVIEW}, {"allow_preview_models": False}, "preview_model"),
        ({"supports_diarization": False}, {"diarization": True}, "diarization"),
        ({"timestamp_modes": {TimestampMode.NONE}}, {"timestamps": "word"}, "timestamps:word"),
        (
            {"transcript_styles": {TranscriptStyle.VERBATIM}},
            {"transcript_style": "clean"},
            "transcript_style:clean",
        ),
        ({"supports_language_detection": False}, {}, "language_detection"),
        ({"supports_phrase_hints": False}, {"phrase_hints": ["acme"]}, "phrase_hints"),
        ({"max_audio_seconds": 60}, {"duration_seconds_hint": 120}, "max_audio_seconds"),
    ],
)
def test_every_capability_dimension_is_negotiated(
    settings: Settings,
    capability: dict[str, object],
    request_overrides: dict[str, object],
    unsatisfied: str,
) -> None:
    router = probe_router(settings, **capability)
    with pytest.raises(OpenTranscribeError) as caught:
        router.route(_request(**request_overrides))
    assert caught.value.response.code == ErrorCode.UNSUPPORTED_CAPABILITY
    assert caught.value.response.details["unsatisfied"] == [unsatisfied]


def test_a_fully_capable_model_satisfies_the_default_request(settings: Settings) -> None:
    """Guard the negotiation tests above: the baseline descriptor must route cleanly."""
    assert probe_router(settings).route(_request())[0].model.key == "probe/probe-1"


def test_unstated_capabilities_bind_to_the_selected_model(settings: Settings) -> None:
    """A bare request must reach a model that supports none of the schema's former defaults."""
    registry = ProviderRegistry([ProbeProvider([descriptor(**GROQ_LIKE)])])
    candidate = Router(registry, settings, routing_config={}).route(_request())[0]
    assert candidate.warnings == ()
    assert candidate.request.diarization is False
    assert candidate.request.transcript_style == TranscriptStyle.VERBATIM
    assert candidate.request.timestamps == TimestampMode.SEGMENT


def test_unstated_capabilities_are_kept_when_the_model_supports_them(settings: Settings) -> None:
    candidate = probe_router(settings).route(_request())[0]
    assert candidate.request.diarization is True
    assert candidate.request.transcript_style == TranscriptStyle.CLEAN
    assert candidate.request.timestamps == TimestampMode.SEGMENT


def test_a_stated_capability_still_excludes_a_model_that_lacks_it(settings: Settings) -> None:
    registry = ProviderRegistry([ProbeProvider([descriptor(**GROQ_LIKE)])])
    with pytest.raises(OpenTranscribeError) as caught:
        Router(registry, settings, routing_config={}).route(_request(diarization=True))
    assert caught.value.response.details["unsatisfied"] == ["diarization"]


def test_non_strict_capabilities_downgrade_without_an_explicit_provider(
    settings: Settings,
) -> None:
    """strict_capabilities=false was inert under provider=auto, which made the flag a no-op."""
    registry = ProviderRegistry([ProbeProvider([descriptor(**GROQ_LIKE)])])
    candidate = Router(registry, settings, routing_config={}).route(
        _request(diarization=True, transcript_style="clean", strict_capabilities=False)
    )[0]
    assert set(candidate.warnings) == {
        "requested_capability_not_supported:diarization",
        "requested_capability_not_supported:transcript_style:clean",
    }
    # The provider is asked only for what its model does, so the metadata stays truthful.
    assert candidate.request.diarization is False
    assert candidate.request.transcript_style == TranscriptStyle.VERBATIM


def test_fixed_routing_returns_only_the_requested_model(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    candidates = Router(registry, settings).route(
        _request(provider="elevenlabs", routing_policy="fixed")
    )
    assert [candidate.model.key for candidate in candidates] == ["elevenlabs/scribe-v2"]


def test_quality_routing_follows_the_configured_ranking(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    candidates = Router(registry, settings).route(
        _request(routing_policy="quality", diarization=False, transcript_style="verbatim")
    )
    assert [candidate.model.key for candidate in candidates] == [
        "microsoft/MAI-Transcribe-2",
        "elevenlabs/scribe-v2",
        "groq/whisper-large-v3",
        "groq/whisper-large-v3-turbo",
    ]


def test_latency_routing_follows_the_configured_ranking(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    candidates = Router(registry, settings).route(
        _request(routing_policy="latency", diarization=False, transcript_style="verbatim")
    )
    assert [candidate.model.key for candidate in candidates] == [
        "groq/whisper-large-v3-turbo",
        "microsoft/MAI-Transcribe-2",
        "elevenlabs/scribe-v2",
        "groq/whisper-large-v3",
    ]


def test_unranked_models_sort_after_ranked_ones(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    router = Router(
        registry, settings, routing_config={"policies": {"quality": ["groq/whisper-large-v3"]}}
    )
    candidates = router.route(
        _request(routing_policy="quality", diarization=False, transcript_style="verbatim")
    )
    assert [candidate.model.key for candidate in candidates] == [
        "groq/whisper-large-v3",
        "elevenlabs/scribe-v2",
        "groq/whisper-large-v3-turbo",
        "microsoft/MAI-Transcribe-2",
    ]


def test_an_explicit_provider_outranks_the_policy_order(settings: Settings) -> None:
    """A caller naming a provider must be served by it, with the policy ordering the fallbacks."""
    registry = ProviderRegistry.from_settings(settings)
    candidates = Router(registry, settings).route(
        _request(
            provider="elevenlabs",
            routing_policy="cost",
            diarization=False,
            transcript_style="verbatim",
        )
    )
    assert candidates[0].model.key == "elevenlabs/scribe-v2"
    assert candidates[1].model.key == "groq/whisper-large-v3-turbo", "cheapest fallback first"


def test_disabled_fallback_yields_a_single_candidate(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    candidates = Router(registry, settings).route(_request(allow_fallback=False))
    assert len(candidates) == 1


def test_an_unconfigured_provider_is_reported(config_dir: object) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={"auth_mode": "none"},
        groq={"api_key": "groq-secret"},
    )
    registry = ProviderRegistry.from_settings(settings)
    with pytest.raises(OpenTranscribeError) as caught:
        Router(registry, settings).route(_request(provider="microsoft"))
    assert caught.value.response.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.response.provider == "microsoft"


def test_a_missing_routing_config_falls_back_to_defaults(tmp_path: Path) -> None:
    assert load_routing(tmp_path / "absent.yaml") == {}
