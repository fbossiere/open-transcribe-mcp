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


def validated(url: str, address: str = "93.184.216.34") -> resolver.ValidatedUrl:
    parsed = httpx.URL(url)
    return resolver.ValidatedUrl(
        url=url,
        scheme="https",
        host=parsed.host,
        port=parsed.port or 443,
        resolved_ips=(address,),
    )


@pytest.mark.asyncio
@respx.mock
async def test_proxy_download_is_bounded_and_deleted(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    validator = AsyncMock(return_value=validated("https://media.example/audio.mp3"))
    monkeypatch.setattr(resolver, "validate_source_url", validator)
    route = respx.get("https://93.184.216.34/audio.mp3", headers={"Host": "media.example"}).mock(
        return_value=httpx.Response(
            200,
            content=b"ID3synthetic-audio",
            headers={"content-type": "audio/mpeg"},
        )
    )
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    path = None
    async with SourceBroker(settings).resolve(
        "https://media.example/audio.mp3", SourceDelivery.PROXY, model
    ) as source:
        path = source.local_path
        assert path
        assert source.size_bytes == len(b"ID3synthetic-audio")
        assert os.path.exists(path)  # noqa: ASYNC240
    assert route.called
    assert route.calls[0].request.extensions["sni_hostname"] == "media.example"
    validator.assert_awaited_once()
    assert path
    assert not os.path.exists(path)  # noqa: ASYNC240


@pytest.mark.asyncio
async def test_auto_delivery_uses_validated_passthrough(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    validator = AsyncMock(return_value=validated("https://media.example/audio.mp3"))
    monkeypatch.setattr(resolver, "validate_source_url", validator)
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    async with SourceBroker(settings).resolve(
        "https://media.example/audio.mp3", SourceDelivery.AUTO, model
    ) as source:
        assert source.delivery == SourceDelivery.PASSTHROUGH
        assert source.local_path is None
    validator.assert_awaited_once()


@pytest.mark.asyncio
@respx.mock
async def test_each_redirect_is_validated(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    validator = AsyncMock(
        side_effect=[
            validated("https://media.example/a"),
            validated("https://media.example/b"),
        ]
    )
    monkeypatch.setattr(resolver, "validate_source_url", validator)
    respx.get("https://93.184.216.34/a").mock(
        return_value=httpx.Response(302, headers={"location": "/b"})
    )
    respx.get("https://93.184.216.34/b").mock(
        return_value=httpx.Response(
            200, content=b"ID3audio", headers={"content-type": "audio/mpeg"}
        )
    )
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    async with SourceBroker(settings).resolve(
        "https://media.example/a", SourceDelivery.PROXY, model
    ):
        pass
    assert validator.await_count == 2  # initial source plus the redirect target


@pytest.mark.asyncio
@respx.mock
async def test_oversized_content_length_is_rejected(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        resolver,
        "validate_source_url",
        AsyncMock(return_value=validated("https://media.example/large")),
    )
    respx.get("https://93.184.216.34/large").mock(
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


@pytest.mark.parametrize(
    ("status_code", "content_length"),
    [(404, None), (200, "invalid"), (200, "-1")],
)
@pytest.mark.asyncio
@respx.mock
async def test_invalid_source_response_is_normalized(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    content_length: str | None,
) -> None:
    url = "https://media.example/invalid"
    monkeypatch.setattr(
        resolver,
        "validate_source_url",
        AsyncMock(return_value=validated(url)),
    )
    headers = {"content-type": "audio/mpeg"}
    if content_length is not None:
        headers["content-length"] = content_length
    respx.get("https://93.184.216.34/invalid").mock(
        return_value=httpx.Response(
            status_code,
            content=b"ID3",
            headers=headers,
        )
    )
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        async with SourceBroker(settings).resolve(url, SourceDelivery.PROXY, model):
            pass
    assert caught.value.response.code == ErrorCode.SOURCE_UNAVAILABLE


def test_passthrough_is_rejected_when_model_requires_upload(settings: Settings) -> None:
    model = (
        ProviderRegistry.from_settings(settings)
        .get_model("groq", "whisper-large-v3")
        .model_copy(update={"supports_url_input": False})
    )
    with pytest.raises(OpenTranscribeError) as caught:
        SourceBroker(settings).select_delivery(SourceDelivery.PASSTHROUGH, model)
    assert caught.value.response.code == ErrorCode.UNSUPPORTED_CAPABILITY
