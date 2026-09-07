import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from open_transcribe.domain.audio import SourceDelivery
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.security import ssrf
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


@pytest.mark.asyncio
@respx.mock
async def test_streamed_body_over_the_limit_is_rejected_without_a_declared_length(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider may omit or understate content-length; the stream itself must be bounded."""
    monkeypatch.setattr(
        resolver,
        "validate_source_url",
        AsyncMock(return_value=validated("https://media.example/unbounded")),
    )
    bounded = settings.model_copy(update={"max_audio_size_mb": 1})
    delivered = 0

    async def oversized() -> AsyncIterator[bytes]:
        nonlocal delivered
        for _ in range(4):
            chunk = b"ID3" + b"\x00" * (512 * 1024)
            delivered += len(chunk)
            yield chunk

    route = respx.get("https://93.184.216.34/unbounded").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "audio/mpeg"}, content=oversized()
        )
    )
    model = ProviderRegistry.from_settings(bounded).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        async with SourceBroker(bounded).resolve(
            "https://media.example/unbounded", SourceDelivery.PROXY, model
        ):
            pass

    assert caught.value.response.code == ErrorCode.SOURCE_TOO_LARGE
    assert "content-length" not in route.calls[0].response.headers
    assert delivered < 4 * (512 * 1024 + 3), "the download must stop before draining the body"


@pytest.mark.asyncio
@respx.mock
async def test_redirect_to_a_prohibited_destination_is_rejected(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The redirect target is re-validated against the SSRF policy, not merely re-resolved."""

    async def resolve(host: str, _: int) -> tuple[str, ...]:
        return ("169.254.169.254",) if host == "metadata.example" else ("93.184.216.34",)

    monkeypatch.setattr(ssrf, "_resolve", resolve)
    respx.get("https://93.184.216.34/start").mock(
        return_value=httpx.Response(302, headers={"location": "https://metadata.example/latest"})
    )
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        async with SourceBroker(settings).resolve(
            "https://media.example/start", SourceDelivery.PROXY, model
        ):
            pass

    assert caught.value.response.code == ErrorCode.SOURCE_URL_REJECTED
    assert "prohibited network destination" in caught.value.response.message


@pytest.mark.asyncio
@respx.mock
async def test_redirect_chain_longer_than_the_limit_is_rejected(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(_: str, __: int) -> tuple[str, ...]:
        return ("93.184.216.34",)

    monkeypatch.setattr(ssrf, "_resolve", resolve)
    limited = settings.model_copy(
        update={"security": settings.security.model_copy(update={"max_redirects": 1})}
    )
    respx.get("https://93.184.216.34/hop-1").mock(
        return_value=httpx.Response(302, headers={"location": "/hop-2"})
    )
    hop_2 = respx.get("https://93.184.216.34/hop-2").mock(
        return_value=httpx.Response(302, headers={"location": "/hop-3"})
    )
    model = ProviderRegistry.from_settings(limited).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        async with SourceBroker(limited).resolve(
            "https://media.example/hop-1", SourceDelivery.PROXY, model
        ):
            pass

    assert caught.value.response.code == ErrorCode.SOURCE_URL_REJECTED
    assert hop_2.called, "the allowed hop is followed before the limit stops the chain"


@pytest.mark.asyncio
@respx.mock
async def test_redirect_without_a_location_is_rejected(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        resolver,
        "validate_source_url",
        AsyncMock(return_value=validated("https://media.example/headless")),
    )
    respx.get("https://93.184.216.34/headless").mock(return_value=httpx.Response(302))
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        async with SourceBroker(settings).resolve(
            "https://media.example/headless", SourceDelivery.PROXY, model
        ):
            pass

    assert caught.value.response.code == ErrorCode.SOURCE_URL_REJECTED


@pytest.mark.asyncio
@respx.mock
async def test_network_failure_during_download_is_retryable_and_redacted(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = "https://media.example/audio.mp3?X-Amz-Signature=must-not-leak"
    monkeypatch.setattr(resolver, "validate_source_url", AsyncMock(return_value=validated(signed)))
    respx.get("https://93.184.216.34/audio.mp3").mock(side_effect=httpx.ConnectError("no route"))
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        async with SourceBroker(settings).resolve(signed, SourceDelivery.PROXY, model):
            pass

    assert caught.value.response.code == ErrorCode.SOURCE_UNAVAILABLE
    assert caught.value.response.retryable
    assert "must-not-leak" not in caught.value.response.model_dump_json()
