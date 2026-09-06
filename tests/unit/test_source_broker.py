import os
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from open_transcribe.domain.audio import SourceDelivery
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.settings import Settings
from open_transcribe.sources import resolver
from open_transcribe.sources.resolver import SourceBroker


@pytest.mark.asyncio
@respx.mock
async def test_proxy_download_is_bounded_and_deleted(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resolver, "validate_source_url", AsyncMock())
    respx.get("https://media.example/audio.mp3").mock(
        return_value=httpx.Response(
            200,
            content=b"ID3synthetic-audio",
            headers={"content-type": "audio/mpeg"},
        )
    )
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    path = None
    async with SourceBroker(settings).resolve(
        "https://media.example/audio.mp3", SourceDelivery.AUTO, model
    ) as source:
        path = source.local_path
        assert path
        assert source.size_bytes == len(b"ID3synthetic-audio")
        assert os.path.exists(path)  # noqa: ASYNC240
    assert path
    assert not os.path.exists(path)  # noqa: ASYNC240


@pytest.mark.asyncio
@respx.mock
async def test_each_redirect_is_validated(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    validator = AsyncMock()
    monkeypatch.setattr(resolver, "validate_source_url", validator)
    respx.get("https://media.example/a").mock(
        return_value=httpx.Response(302, headers={"location": "/b"})
    )
    respx.get("https://media.example/b").mock(
        return_value=httpx.Response(
            200, content=b"ID3audio", headers={"content-type": "audio/mpeg"}
        )
    )
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    async with SourceBroker(settings).resolve(
        "https://media.example/a", SourceDelivery.PROXY, model
    ):
        pass
    assert validator.await_count == 3  # initial source plus both connection targets


@pytest.mark.asyncio
@respx.mock
async def test_oversized_content_length_is_rejected(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resolver, "validate_source_url", AsyncMock())
    respx.get("https://media.example/large").mock(
        return_value=httpx.Response(
            200,
            content=b"ID3",
            headers={
                "content-type": "audio/mpeg",
                "content-length": str(settings.max_audio_bytes + 1),
            },
        )
    )
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        async with SourceBroker(settings).resolve(
            "https://media.example/large", SourceDelivery.PROXY, model
        ):
            pass
    assert caught.value.response.code == ErrorCode.SOURCE_TOO_LARGE


def test_passthrough_is_rejected_when_model_requires_upload(settings: Settings) -> None:
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        SourceBroker(settings).select_delivery(SourceDelivery.PASSTHROUGH, model)
    assert caught.value.response.code == ErrorCode.UNSUPPORTED_CAPABILITY
