import pytest

from open_transcribe.domain.audio import TranscribeAudioRequest
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.routing.router import Router
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
    request = _request(provider="groq", model="whisper-large-v3", transcript_style="verbatim")
    with pytest.raises(OpenTranscribeError) as caught:
        Router(registry, settings).route(request)
    assert caught.value.response.code == ErrorCode.UNSUPPORTED_CAPABILITY
    assert "diarization" in caught.value.response.details["unsupported"]


def test_non_strict_capability_emits_warning(settings: Settings) -> None:
    registry = ProviderRegistry.from_settings(settings)
    request = _request(
        provider="groq",
        model="whisper-large-v3",
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
