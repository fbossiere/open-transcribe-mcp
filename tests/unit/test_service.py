from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from open_transcribe.domain.audio import ResolvedAudioSource, SourceDelivery, TranscribeAudioRequest
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError, ProviderError
from open_transcribe.domain.transcript import (
    CanonicalTranscript,
    InlineTranscriptionResult,
    StoredTranscriptionResult,
    TranscriptionMetadata,
    UsageInfo,
)
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.result_store.memory import MemoryResultStore
from open_transcribe.routing.router import Router
from open_transcribe.service import TranscriptionService
from open_transcribe.settings import Settings


class FakeBroker:
    def __init__(self, size_bytes: int | None = None) -> None:
        self.size_bytes = size_bytes

    @asynccontextmanager
    async def resolve(self, *_: object) -> AsyncIterator[ResolvedAudioSource]:
        yield ResolvedAudioSource(
            original_url="https://media.example/audio.mp3",
            delivery=SourceDelivery.PASSTHROUGH,
            size_bytes=self.size_bytes,
        )


def canonical(provider: str = "microsoft", model: str = "MAI-Transcribe-2") -> CanonicalTranscript:
    request = TranscribeAudioRequest.model_validate(
        {"source": {"url": "https://media.example/audio.mp3"}}
    )
    return CanonicalTranscript(
        transcript_id="tr_test",
        provider=provider,
        model=model,
        source_duration_ms=1000,
        text="hello world",
        segments=[],
        usage=UsageInfo(audio_seconds=1),
        metadata=TranscriptionMetadata(
            diarization=True,
            timestamps=request.timestamps,
            transcript_style=request.transcript_style,
        ),
    )


def service(settings: Settings, broker: FakeBroker | None = None) -> TranscriptionService:
    registry = ProviderRegistry.from_settings(settings)
    return TranscriptionService(
        settings,
        registry,
        Router(registry, settings),
        broker or FakeBroker(),  # type: ignore[arg-type]
        MemoryResultStore(ttl_seconds=60, cursor_secret="secret"),
    )


@pytest.mark.asyncio
async def test_inline_transcription(settings: Settings) -> None:
    app = service(settings)
    provider = app.registry.get_provider("microsoft")
    provider.transcribe = AsyncMock(return_value=canonical())  # type: ignore[method-assign]
    result = await app.transcribe(
        TranscribeAudioRequest.model_validate(
            {"source": {"url": "https://media.example/audio.mp3"}}
        )
    )
    assert isinstance(result, InlineTranscriptionResult)
    assert result.text == "hello world"


@pytest.mark.asyncio
async def test_transient_failure_falls_back(settings: Settings) -> None:
    app = service(settings)
    microsoft = app.registry.get_provider("microsoft")
    eleven = app.registry.get_provider("elevenlabs")
    microsoft.transcribe = AsyncMock(  # type: ignore[method-assign]
        side_effect=ProviderError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "down",
            provider="microsoft",
            model="MAI-Transcribe-2",
            retryable=True,
            details={"reason": "provider_http_503"},
        )
    )
    eleven.transcribe = AsyncMock(  # type: ignore[method-assign]
        return_value=canonical("elevenlabs", "scribe-v2")
    )
    result = await app.transcribe(
        TranscribeAudioRequest.model_validate(
            {"source": {"url": "https://media.example/audio.mp3"}}
        )
    )
    assert isinstance(result, InlineTranscriptionResult)
    assert result.provider == "elevenlabs"
    assert result.metadata.fallback_used
    assert result.metadata.fallback_history[0].provider == "microsoft"


@pytest.mark.asyncio
async def test_stored_result_can_be_chunked_and_deleted(settings: Settings) -> None:
    app = service(settings)
    provider = app.registry.get_provider("microsoft")
    provider.transcribe = AsyncMock(return_value=canonical())  # type: ignore[method-assign]
    result = await app.transcribe(
        TranscribeAudioRequest.model_validate(
            {
                "source": {"url": "https://media.example/audio.mp3"},
                "result_mode": "stored",
            }
        )
    )
    assert isinstance(result, StoredTranscriptionResult)
    chunk = await app.get_chunk(result.transcript_id, None, 100, "text")
    assert chunk.content == "hello world"
    assert (await app.delete(result.transcript_id)).deleted


def test_cost_estimate_and_model_listing(settings: Settings) -> None:
    app = service(settings)
    assert len(app.list_models()) == 4
    assert len(app.list_models(configured_only=True)) == 4
    estimate = app.estimate_cost(3600, "groq", "whisper-large-v3-turbo")
    assert estimate.estimated_cost_usd == 0.04


def test_cost_ceiling_is_enforced(settings: Settings) -> None:
    limited = settings.model_copy(update={"max_request_cost_usd": 0.000001})
    app = service(limited)
    request = TranscribeAudioRequest.model_validate(
        {
            "source": {"url": "https://media.example/audio.mp3"},
            "duration_seconds_hint": 3600,
        }
    )
    with pytest.raises(Exception, match="cost exceeds"):
        app._enforce_preflight_limits(
            request, app.registry.get_model("microsoft", "MAI-Transcribe-2")
        )


def transient(provider: str, model: str) -> ProviderError:
    return ProviderError(
        ErrorCode.PROVIDER_UNAVAILABLE,
        "down",
        provider=provider,
        model=model,
        retryable=True,
        details={"reason": "provider_http_503"},
    )


@pytest.mark.asyncio
async def test_a_non_retryable_provider_error_is_not_retried_elsewhere(
    settings: Settings,
) -> None:
    """SPEC 20.2 keeps an authentication failure from being masked by another provider."""
    app = service(settings)
    app.registry.get_provider("microsoft").transcribe = AsyncMock(  # type: ignore[method-assign]
        side_effect=ProviderError(
            ErrorCode.PROVIDER_AUTHENTICATION_FAILED,
            "rejected credentials",
            provider="microsoft",
            model="MAI-Transcribe-2",
            retryable=False,
        )
    )
    eleven = AsyncMock()
    app.registry.get_provider("elevenlabs").transcribe = eleven  # type: ignore[method-assign]

    with pytest.raises(ProviderError) as caught:
        await app.transcribe(
            TranscribeAudioRequest.model_validate(
                {"source": {"url": "https://media.example/audio.mp3"}}
            )
        )

    assert caught.value.response.code == ErrorCode.PROVIDER_AUTHENTICATION_FAILED
    eleven.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_disabled_fallback_reraises_a_transient_failure(settings: Settings) -> None:
    app = service(settings)
    app.registry.get_provider("microsoft").transcribe = AsyncMock(  # type: ignore[method-assign]
        side_effect=transient("microsoft", "MAI-Transcribe-2")
    )
    eleven = AsyncMock()
    app.registry.get_provider("elevenlabs").transcribe = eleven  # type: ignore[method-assign]

    with pytest.raises(ProviderError) as caught:
        await app.transcribe(
            TranscribeAudioRequest.model_validate(
                {"source": {"url": "https://media.example/audio.mp3"}, "allow_fallback": False}
            )
        )

    assert caught.value.response.code == ErrorCode.PROVIDER_UNAVAILABLE
    eleven.assert_not_awaited()


@pytest.mark.asyncio
async def test_every_candidate_failing_reports_each_attempt(settings: Settings) -> None:
    app = service(settings)
    for provider_id in ("microsoft", "elevenlabs"):
        app.registry.get_provider(provider_id).transcribe = AsyncMock(  # type: ignore[method-assign]
            side_effect=transient(provider_id, "any")
        )

    with pytest.raises(OpenTranscribeError) as caught:
        await app.transcribe(
            TranscribeAudioRequest.model_validate(
                {"source": {"url": "https://media.example/audio.mp3"}}
            )
        )

    response = caught.value.response
    assert response.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert response.retryable
    attempts = response.details["attempts"]
    assert [attempt["provider"] for attempt in attempts] == ["microsoft", "elevenlabs"]
    assert {attempt["reason"] for attempt in attempts} == {"provider_http_503"}


@pytest.mark.asyncio
async def test_a_source_over_the_model_limit_is_not_retried_elsewhere(
    settings: Settings,
) -> None:
    """SPEC 20.2 lists an oversized source as non-eligible, so no other model is tried."""
    app = service(settings, FakeBroker(size_bytes=200 * 1024 * 1024))
    groq = AsyncMock()
    app.registry.get_provider("groq").transcribe = groq  # type: ignore[method-assign]

    with pytest.raises(OpenTranscribeError) as caught:
        await app.transcribe(
            TranscribeAudioRequest.model_validate(
                {
                    "source": {"url": "https://media.example/audio.mp3"},
                    "provider": "groq",
                    "diarization": False,
                    "transcript_style": "verbatim",
                }
            )
        )

    assert caught.value.response.code == ErrorCode.SOURCE_TOO_LARGE
    assert caught.value.response.provider == "groq"
    groq.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_duration_hint_over_the_limit_is_refused_before_any_provider_call(
    settings: Settings,
) -> None:
    limited = settings.model_copy(update={"max_audio_duration_seconds": 60})
    app = service(limited)
    provider = AsyncMock()
    app.registry.get_provider("microsoft").transcribe = provider  # type: ignore[method-assign]

    with pytest.raises(OpenTranscribeError) as caught:
        await app.transcribe(
            TranscribeAudioRequest.model_validate(
                {
                    "source": {"url": "https://media.example/audio.mp3"},
                    "duration_seconds_hint": 120,
                }
            )
        )

    assert caught.value.response.code == ErrorCode.SOURCE_DURATION_EXCEEDED
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_longer_than_the_limit_is_refused_after_transcription(
    settings: Settings,
) -> None:
    """The hint is optional, so the provider-reported duration is the enforced one."""
    limited = settings.model_copy(update={"max_audio_duration_seconds": 60})
    app = service(limited)
    transcript = canonical()
    transcript.source_duration_ms = 120_000
    app.registry.get_provider("microsoft").transcribe = AsyncMock(  # type: ignore[method-assign]
        return_value=transcript
    )

    with pytest.raises(OpenTranscribeError) as caught:
        await app.transcribe(
            TranscribeAudioRequest.model_validate(
                {"source": {"url": "https://media.example/audio.mp3"}}
            )
        )

    assert caught.value.response.code == ErrorCode.SOURCE_DURATION_EXCEEDED


@pytest.mark.asyncio
async def test_a_cost_ceiling_fails_closed_without_pricing_metadata(
    settings: Settings, tmp_path: Path
) -> None:
    """An unpriced model must not slip past an operator's configured cost ceiling."""
    unpriced = settings.model_copy(update={"config_dir": tmp_path, "max_request_cost_usd": 10.0})
    app = service(unpriced)
    provider = AsyncMock()
    app.registry.get_provider("microsoft").transcribe = provider  # type: ignore[method-assign]
    assert app.registry.get_model("microsoft", "MAI-Transcribe-2").pricing is None

    with pytest.raises(OpenTranscribeError) as caught:
        await app.transcribe(
            TranscribeAudioRequest.model_validate(
                {
                    "source": {"url": "https://media.example/audio.mp3"},
                    "duration_seconds_hint": 60,
                }
            )
        )

    assert caught.value.response.code == ErrorCode.COST_LIMIT_EXCEEDED
    assert "Pricing metadata" in caught.value.response.message
    provider.assert_not_awaited()


def test_a_duration_hint_without_a_cost_ceiling_is_allowed(settings: Settings) -> None:
    app = service(settings)
    assert settings.max_request_cost_usd is None
    app._enforce_preflight_limits(
        TranscribeAudioRequest.model_validate(
            {"source": {"url": "https://media.example/audio.mp3"}, "duration_seconds_hint": 60}
        ),
        app.registry.get_model("microsoft", "MAI-Transcribe-2"),
    )


def test_an_estimate_under_the_ceiling_is_allowed(settings: Settings) -> None:
    generous = settings.model_copy(update={"max_request_cost_usd": 100.0})
    app = service(generous)
    app._enforce_preflight_limits(
        TranscribeAudioRequest.model_validate(
            {"source": {"url": "https://media.example/audio.mp3"}, "duration_seconds_hint": 60}
        ),
        app.registry.get_model("microsoft", "MAI-Transcribe-2"),
    )


@pytest.mark.parametrize("duration_seconds", [0, -1, -0.5, 21_601, 1_000_000])
def test_a_cost_estimate_outside_the_configured_limits_is_refused(
    settings: Settings, duration_seconds: float
) -> None:
    app = service(settings)
    with pytest.raises(OpenTranscribeError) as caught:
        app.estimate_cost(duration_seconds, "microsoft", "MAI-Transcribe-2")
    assert caught.value.response.code == ErrorCode.SOURCE_DURATION_EXCEEDED


@pytest.mark.parametrize("duration_seconds", [0.5, 1, 3600, 21_600])
def test_a_cost_estimate_inside_the_configured_limits_is_returned(
    settings: Settings, duration_seconds: float
) -> None:
    estimate = service(settings).estimate_cost(duration_seconds, "microsoft", "MAI-Transcribe-2")
    assert estimate.estimated_cost_usd is not None
    assert estimate.estimated_cost_usd > 0
