"""Fuzzing of URL validation and redaction (SPEC 46).

The campaign is seeded so a release gate stays deterministic. Override
``OT_FUZZ_SEED`` and ``OT_FUZZ_ITERATIONS`` to run a wider one locally.
"""

import os
import random

import pytest

from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.security import ssrf
from open_transcribe.security.redaction import UNPARSEABLE_URL, redact_url, safe_source_fields
from open_transcribe.security.ssrf import is_prohibited_ip, validate_source_url

SEED = int(os.environ.get("OT_FUZZ_SEED", "20260907"))
ITERATIONS = int(os.environ.get("OT_FUZZ_ITERATIONS", "2000"))

SCHEMES = (
    "https://",
    "http://",
    "HTTPS://",
    "file://",
    "ftp://",
    "gopher://",
    "//",
    "",
    "https:/",
    "https:",
    "https:///",
)

# Authority fragments chosen to break IDNA encoding, bracket parsing, NFKC
# normalization, and the private-address checks.
FRAGMENTS = (
    "a",
    "example",
    "com",
    ".",
    "..",
    "...",
    "-",
    "_",
    "~",
    " ",
    "\t",
    "\n",
    "\r",
    "@",
    ":",
    ":443",
    ":0",
    ":99999",
    ":-1",
    "[",
    "]",
    "[::1]",
    "?",
    "#",
    "%",
    "%00",
    "%2e",
    "%2f",
    "​",
    "­",
    "。",
    "﷐",
    "℀",
    "Ā",
    "é",
    "é",
    "あ",
    "xn--",
    "xn--a",
    "a" * 64,
    "a" * 300,
    "localhost",
    "LOCALHOST",
    "127.0.0.1",
    "0177.0.0.1",
    "0x7f.0.0.1",
    "169.254.169.254",
    "10.0.0.1",
    "::1",
    "user:pass@",
)

PATHS = ("", "/", "/audio.mp3", "/a?token=secret", "/a#frag", "?x=1", "//a", "/%00")

# One stable answer per hostname, mixing global, prohibited, mixed and empty results.
ANSWERS = (
    ("1.1.1.1",),
    ("8.8.8.8", "2606:4700:4700::1111"),
    ("127.0.0.1",),
    ("169.254.169.254",),
    ("1.1.1.1", "10.0.0.1"),
    (),
)


def urls() -> list[str]:
    rng = random.Random(SEED)  # noqa: S311
    generated = []
    for _ in range(ITERATIONS):
        authority = "".join(rng.choices(FRAGMENTS, k=rng.randint(1, 6)))
        generated.append(rng.choice(SCHEMES) + authority + rng.choice(PATHS))
    return generated


@pytest.fixture
def stub_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(host: str, _: int) -> tuple[str, ...]:
        return ANSWERS[sum(host.encode("utf-8", "ignore")) % len(ANSWERS)]

    monkeypatch.setattr(ssrf, "_resolve", resolve)


@pytest.mark.asyncio
async def test_validation_only_ever_raises_a_project_error(stub_dns: None) -> None:
    """A malformed URL is a source rejection, never an unhandled server fault."""
    leaked: list[tuple[str, str]] = []
    for url in urls():
        try:
            await validate_source_url(url)
        except OpenTranscribeError:
            continue
        except Exception as exc:
            leaked.append((url, f"{type(exc).__name__}: {exc}"))
    assert leaked == []


@pytest.mark.asyncio
async def test_an_accepted_url_never_resolves_to_a_prohibited_address(stub_dns: None) -> None:
    """The SSRF invariant: acceptance implies every resolved address is globally routable."""
    for url in urls():
        try:
            result = await validate_source_url(url)
        except OpenTranscribeError:
            continue
        assert result.resolved_ips
        assert not [ip for ip in result.resolved_ips if is_prohibited_ip(ip)], url
        assert result.scheme == "https", url
        assert result.host, url


@pytest.mark.asyncio
async def test_an_accepted_url_pins_a_connection_target(stub_dns: None) -> None:
    """Every accepted URL must yield a usable IP-pinned target and original authority."""
    for url in urls():
        try:
            result = await validate_source_url(url)
        except OpenTranscribeError:
            continue
        target, authority = result.connection_target(result.resolved_ips[0])
        assert target.startswith("https://")
        assert "#" not in target
        assert authority


def test_redaction_never_raises_and_never_echoes_a_query() -> None:
    for url in urls():
        redacted = redact_url(url)
        assert "token=secret" not in redacted
        fields = safe_source_fields(url)
        assert len(fields["source_path_hash"]) == 16


def test_an_unparseable_url_degrades_to_a_placeholder() -> None:
    assert redact_url("https://℀.com/a?token=secret") == UNPARSEABLE_URL
    assert safe_source_fields("https://℀.com/a") == {
        "source_host": "",
        "source_path_hash": safe_source_fields("")["source_path_hash"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://a..b/audio.mp3",
        "https://" + "a" * 64 + ".com/audio.mp3",
        "https://。example.com/audio.mp3",
        "https://" + "é" * 100 + ".com/audio.mp3",
        "https://​.com/audio.mp3",
        "https://­.com/audio.mp3",
        "https://﷐.com/audio.mp3",
        "https://.../audio.mp3",
        "https://[not-an-ip]/audio.mp3",
        "https://℀.com/audio.mp3",
    ],
)
async def test_malformed_hostnames_are_rejected_cleanly(stub_dns: None, url: str) -> None:
    """Regression corpus: each of these escaped as UnicodeError or ValueError."""
    with pytest.raises(OpenTranscribeError) as caught:
        await validate_source_url(url)
    assert caught.value.response.code == ErrorCode.SOURCE_URL_REJECTED


@pytest.mark.asyncio
async def test_private_addresses_are_allowed_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(_: str, __: int) -> tuple[str, ...]:
        return ("10.0.0.1",)

    monkeypatch.setattr(ssrf, "_resolve", resolve)
    result = await validate_source_url("https://internal.example/a.mp3", allow_private_urls=True)
    assert result.resolved_ips == ("10.0.0.1",)


@pytest.mark.asyncio
async def test_a_hostname_with_no_addresses_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(_: str, __: int) -> tuple[str, ...]:
        return ()

    monkeypatch.setattr(ssrf, "_resolve", resolve)
    with pytest.raises(OpenTranscribeError) as caught:
        await validate_source_url("https://void.example/a.mp3")
    assert caught.value.response.code == ErrorCode.SOURCE_UNAVAILABLE


@pytest.mark.asyncio
async def test_an_unresolvable_hostname_is_unavailable() -> None:
    with pytest.raises(OpenTranscribeError) as caught:
        await validate_source_url("https://nonexistent.invalid/a.mp3")
    assert caught.value.response.code == ErrorCode.SOURCE_UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["file", "ftp", "gopher", "data"])
async def test_non_http_schemes_are_rejected(scheme: str) -> None:
    with pytest.raises(OpenTranscribeError, match="HTTP"):
        await validate_source_url(f"{scheme}://example.com/a.mp3")
