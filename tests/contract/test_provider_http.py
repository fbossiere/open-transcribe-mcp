from pathlib import Path

import httpx
import pytest
import respx

from open_transcribe.domain.audio import (
    ResolvedAudioSource,
    ResolvedTranscribeRequest,
    SourceDelivery,
)
from open_transcribe.providers.elevenlabs.adapter import ElevenLabsProvider
from open_transcribe.providers.groq.adapter import GroqProvider
from open_transcribe.providers.microsoft.adapter import MicrosoftProvider
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.settings import Settings


def adapters(settings: Settings) -> tuple[MicrosoftProvider, ElevenLabsProvider, GroqProvider]:
    registry = ProviderRegistry.from_settings(settings)
    return (
        registry.get_provider("microsoft"),  # type: ignore[return-value]
        registry.get_provider("elevenlabs"),  # type: ignore[return-value]
        registry.get_provider("groq"),  # type: ignore[return-value]
    )


def request(**overrides: object) -> ResolvedTranscribeRequest:
    data: dict[str, object] = {
        "source": {"url": "https://media.example/audio.mp3"},
        "diarization": True,
        "transcript_style": "verbatim",
        "timestamps": "word",
    }
    data.update(overrides)
    return ResolvedTranscribeRequest.model_validate(data)


@pytest.mark.asyncio
@respx.mock
async def test_microsoft_url_passthrough(settings: Settings) -> None:
    microsoft, _, _ = adapters(settings)
    route = respx.post("https://speech.example.com/speechtotext/transcriptions:transcribe").mock(
        return_value=httpx.Response(
            200,
            json={
                "durationMilliseconds": 1000,
                "combinedPhrases": [{"text": "Hello"}],
                "phrases": [],
            },
            headers={"request-id": "microsoft-id"},
        )
    )
    result = await microsoft.transcribe(
        request(),
        ResolvedAudioSource(
            original_url="https://media.example/audio.mp3",
            delivery=SourceDelivery.PASSTHROUGH,
        ),
        microsoft.list_models()[0],
    )
    assert route.called
    assert result.text == "Hello"
    assert result.metadata.provider_request_id == "microsoft-id"


@pytest.mark.asyncio
@respx.mock
async def test_groq_url_passthrough_requests_word_and_segment_timestamps(
    settings: Settings,
) -> None:
    _, _, groq = adapters(settings)
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(
        return_value=httpx.Response(
            200,
            json={
                "language": "en",
                "duration": 1,
                "text": "Hello",
                "segments": [{"start": 0, "end": 1, "text": "Hello"}],
                "words": [{"start": 0, "end": 1, "word": "Hello"}],
            },
        )
    )
    result = await groq.transcribe(
        request(diarization=False),
        ResolvedAudioSource(
            original_url="https://media.example/audio.mp3?signature=secret",
            delivery=SourceDelivery.PASSTHROUGH,
        ),
        groq.list_models()[0],
    )
    assert result.segments
    assert result.segments[0].words
    body = route.calls[0].request.content.decode()
    assert 'name="url"' in body
    assert "https://media.example/audio.mp3?signature=secret" in body
    assert body.count('name="timestamp_granularities[]"') == 2
    assert "word" in body
    assert "segment" in body


@pytest.mark.asyncio
@respx.mock
async def test_elevenlabs_url_passthrough(settings: Settings) -> None:
    _, eleven, _ = adapters(settings)
    route = respx.post("https://api.elevenlabs.io/v1/speech-to-text").mock(
        return_value=httpx.Response(
            200,
            json={"language_code": "en", "text": "Hello", "words": []},
        )
    )
    result = await eleven.transcribe(
        request(),
        ResolvedAudioSource(
            original_url="https://media.example/audio.mp3",
            delivery=SourceDelivery.PASSTHROUGH,
        ),
        eleven.list_models()[0],
    )
    assert route.called
    assert result.text == "Hello"
    assert route.calls[0].request.url.params["enable_logging"] == "false"


@pytest.mark.asyncio
@respx.mock
async def test_groq_proxy_upload(settings: Settings, tmp_path: Path) -> None:
    _, _, groq = adapters(settings)
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"ID3synthetic-test")
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(
        return_value=httpx.Response(
            200,
            json={
                "language": "en",
                "duration": 1,
                "text": "Hello",
                "segments": [],
                "words": [],
            },
        )
    )
    result = await groq.transcribe(
        request(diarization=False),
        ResolvedAudioSource(
            original_url="https://media.example/audio.mp3",
            delivery=SourceDelivery.PROXY,
            local_path=str(audio),
            media_type="audio/mpeg",
        ),
        groq.list_models()[0],
    )
    assert route.called
    assert result.text == "Hello"


@pytest.mark.asyncio
@respx.mock
async def test_provider_auth_error_is_normalized(settings: Settings) -> None:
    _, eleven, _ = adapters(settings)
    respx.post("https://api.elevenlabs.io/v1/speech-to-text").mock(
        return_value=httpx.Response(401, json={"detail": "do not leak me"})
    )
    with pytest.raises(Exception, match="rejected its configured credentials"):
        await eleven.transcribe(
            request(),
            ResolvedAudioSource(
                original_url="https://media.example/audio.mp3",
                delivery=SourceDelivery.PASSTHROUGH,
            ),
            eleven.list_models()[0],
        )
