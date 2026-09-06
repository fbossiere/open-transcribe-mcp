import pytest

from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.security import ssrf
from open_transcribe.security.redaction import redact_url, safe_source_fields
from open_transcribe.security.ssrf import is_prohibited_ip, validate_source_url


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "172.16.1.1", "192.168.1.1", "169.254.169.254", "::1", "fe80::1"],
)
def test_private_and_metadata_addresses_are_prohibited(address: str) -> None:
    assert is_prohibited_ip(address)


@pytest.mark.parametrize("address", ["1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"])
def test_global_addresses_are_allowed(address: str) -> None:
    assert not is_prohibited_ip(address)


@pytest.mark.asyncio
async def test_localhost_is_rejected_without_dns() -> None:
    with pytest.raises(OpenTranscribeError) as caught:
        await validate_source_url("https://localhost/audio.mp3")
    assert caught.value.response.code == ErrorCode.SOURCE_URL_REJECTED


@pytest.mark.asyncio
async def test_http_is_rejected_by_default() -> None:
    with pytest.raises(OpenTranscribeError, match="HTTPS"):
        await validate_source_url("http://example.com/audio.mp3")


@pytest.mark.asyncio
async def test_userinfo_is_rejected() -> None:
    with pytest.raises(OpenTranscribeError, match="User-info"):
        await validate_source_url("https://user:pass@example.com/audio.mp3")


def test_signed_url_is_redacted() -> None:
    value = redact_url("https://bucket.example/a.mp3?X-Amz-Signature=secret#fragment")
    assert "secret" not in value
    assert "fragment" not in value
    assert value == "https://bucket.example/a.mp3?[REDACTED]"


def test_safe_source_fields_contain_no_query() -> None:
    fields = safe_source_fields("https://bucket.example/private/a.mp3?token=secret")
    assert fields["source_host"] == "bucket.example"
    assert "secret" not in repr(fields)
    assert len(fields["source_path_hash"]) == 16


@pytest.mark.asyncio
async def test_public_resolution_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    async def public(_: str, __: int) -> tuple[str, ...]:
        return ("1.1.1.1",)

    monkeypatch.setattr(ssrf, "_resolve", public)
    result = await validate_source_url("https://example.com/audio.mp3")
    assert result.host == "example.com"
    assert result.port == 443
    assert result.resolved_ips == ("1.1.1.1",)


def test_validated_url_pins_connection_and_preserves_original_authority() -> None:
    validated = ssrf.ValidatedUrl(
        url="https://media.example:8443/audio.mp3?signature=secret#ignored",
        scheme="https",
        host="media.example",
        port=8443,
        resolved_ips=("2001:4860:4860::8888",),
    )
    target, authority = validated.connection_target("2001:4860:4860::8888")
    assert target == "https://[2001:4860:4860::8888]:8443/audio.mp3?signature=secret"
    assert authority == "media.example:8443"


@pytest.mark.asyncio
async def test_invalid_port_is_a_security_rejection() -> None:
    with pytest.raises(OpenTranscribeError) as caught:
        await validate_source_url("https://example.com:99999/audio.mp3")
    assert caught.value.response.code == ErrorCode.SOURCE_URL_REJECTED


@pytest.mark.asyncio
async def test_private_dns_answer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def private(_: str, __: int) -> tuple[str, ...]:
        return ("169.254.169.254",)

    monkeypatch.setattr(ssrf, "_resolve", private)
    with pytest.raises(OpenTranscribeError) as caught:
        await validate_source_url("https://metadata.example/audio.mp3")
    assert caught.value.response.code == ErrorCode.SOURCE_URL_REJECTED


@pytest.mark.asyncio
async def test_host_allowlist_is_enforced() -> None:
    with pytest.raises(OpenTranscribeError, match="allow-listed"):
        await validate_source_url(
            "https://example.com/audio.mp3", allowed_hosts=["media.example.com"]
        )
