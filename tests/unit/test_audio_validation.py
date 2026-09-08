"""Content-type and magic-byte validation of a proxied download (SPEC 29.6)."""

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
from tests.unit.test_source_broker import validated

MP3 = b"ID3\x04\x00\x00\x00"
RIFF = b"RIFF\x24\x08\x00\x00WAVE"
OGG = b"OggS\x00\x02\x00\x00"
FLAC = b"fLaC\x00\x00\x00\x22"
MATROSKA = b"\x1aE\xdf\xa3\x01\x00\x00\x00"
MP4 = b"\x00\x00\x00\x20ftypM4A "
MP3_SYNC = b"\xff\xfb\x90\x00\x00\x00\x00\x00"


def validate(prefix: bytes, media_type: str | None, size: int | None = None) -> None:
    SourceBroker._validate_audio(prefix, media_type, size if size is not None else len(prefix))


@pytest.mark.parametrize(
    ("prefix", "media_type"),
    [
        (MP3, "audio/mpeg"),
        (RIFF, "audio/wav"),
        (OGG, "audio/ogg"),
        (FLAC, "audio/flac"),
        (MATROSKA, "audio/webm"),
        (MP4, "audio/mp4"),
        (MP3_SYNC, "audio/mpeg"),
        (MP3, "video/mp4"),
        (MP3, "audio/mpeg; charset=binary"),
        (MP3, "AUDIO/MPEG"),
        (MP3, "  audio/mpeg  "),
    ],
)
def test_a_declared_audio_type_is_accepted(prefix: bytes, media_type: str) -> None:
    validate(prefix, media_type)


@pytest.mark.parametrize(
    "prefix",
    [MP3, RIFF, OGG, FLAC, MATROSKA, MP4, MP3_SYNC, b"\xff\xf3\x90\x00", b"\xff\xf2\x90\x00"],
)
@pytest.mark.parametrize(
    "media_type", ["application/octet-stream", "binary/octet-stream", "", None]
)
def test_an_opaque_type_is_accepted_when_the_magic_bytes_match(
    prefix: bytes, media_type: str | None
) -> None:
    """A provider that will not commit to a type is trusted only if the bytes agree."""
    validate(prefix, media_type)


@pytest.mark.parametrize("media_type", ["application/octet-stream", "", None])
def test_an_opaque_type_is_rejected_when_the_magic_bytes_do_not_match(
    media_type: str | None,
) -> None:
    with pytest.raises(OpenTranscribeError) as caught:
        validate(b"<!DOCTYPE html><html>", media_type)
    assert caught.value.response.code == ErrorCode.INVALID_AUDIO
    assert "supported audio" in caught.value.response.message


@pytest.mark.parametrize(
    "media_type",
    ["text/html", "application/json", "text/plain", "application/pdf", "image/png"],
)
def test_a_non_audio_type_is_rejected_even_with_audio_magic_bytes(media_type: str) -> None:
    """A declared non-audio type is refused outright; sniffing cannot override it."""
    with pytest.raises(OpenTranscribeError) as caught:
        validate(MP3, media_type)
    assert caught.value.response.code == ErrorCode.INVALID_AUDIO


def test_an_empty_source_is_rejected() -> None:
    with pytest.raises(OpenTranscribeError) as caught:
        validate(b"", "audio/mpeg", size=0)
    assert caught.value.response.code == ErrorCode.INVALID_AUDIO
    assert "empty" in caught.value.response.message


def test_a_truncated_prefix_does_not_read_out_of_range() -> None:
    """The ftyp probe reads bytes 4 to 8, so a shorter prefix must not raise IndexError."""
    with pytest.raises(OpenTranscribeError) as caught:
        validate(b"ftyp", "application/octet-stream")
    assert caught.value.response.code == ErrorCode.INVALID_AUDIO


@pytest.mark.parametrize(
    ("prefix", "media_type", "expected_message"),
    [(b"", "audio/mpeg", "empty"), (b"<html>", "text/html", "supported audio")],
)
@pytest.mark.asyncio
@respx.mock
async def test_content_validation_is_wired_into_the_proxy_download(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    prefix: bytes,
    media_type: str,
    expected_message: str,
) -> None:
    monkeypatch.setattr(
        resolver,
        "validate_source_url",
        AsyncMock(return_value=validated("https://media.example/decoy")),
    )
    respx.get("https://93.184.216.34/decoy").mock(
        return_value=httpx.Response(200, content=prefix, headers={"content-type": media_type})
    )
    model = ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3")
    with pytest.raises(OpenTranscribeError) as caught:
        async with SourceBroker(settings).resolve(
            "https://media.example/decoy", SourceDelivery.PROXY, model
        ):
            pass

    assert caught.value.response.code == ErrorCode.INVALID_AUDIO
    assert expected_message in caught.value.response.message
