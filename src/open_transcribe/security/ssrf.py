import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    url: str
    scheme: str
    host: str
    port: int
    resolved_ips: tuple[str, ...]

    def connection_target(self, address: str) -> tuple[str, str]:
        """Return an IP-pinned URL and the original authority for Host/SNI."""
        parts = urlsplit(self.url)
        ip = ipaddress.ip_address(address)
        target_host = f"[{ip.compressed}]" if ip.version == 6 else ip.compressed
        default_port = 443 if self.scheme == "https" else 80
        target_authority = (
            target_host if self.port == default_port else f"{target_host}:{self.port}"
        )
        host = f"[{self.host}]" if ":" in self.host else self.host
        original_authority = host if self.port == default_port else f"{host}:{self.port}"
        target = parts._replace(netloc=target_authority, fragment="").geturl()
        return target, original_authority


def is_prohibited_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not ip.is_global


async def _resolve(host: str, port: int) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    try:
        records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OpenTranscribeError(
            ErrorCode.SOURCE_UNAVAILABLE, "The audio source hostname could not be resolved."
        ) from exc
    return tuple(sorted({record[4][0] for record in records}))


async def validate_source_url(
    url: str,
    *,
    require_https: bool = True,
    allow_private_urls: bool = False,
    allowed_hosts: list[str] | None = None,
) -> ValidatedUrl:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise OpenTranscribeError(
            ErrorCode.SOURCE_URL_REJECTED, "Only HTTP(S) sources are allowed."
        )
    if require_https and parts.scheme != "https":
        raise OpenTranscribeError(ErrorCode.SOURCE_URL_REJECTED, "The audio source must use HTTPS.")
    if parts.username or parts.password:
        raise OpenTranscribeError(
            ErrorCode.SOURCE_URL_REJECTED, "User-info credentials are not allowed in source URLs."
        )
    if not parts.hostname:
        raise OpenTranscribeError(
            ErrorCode.SOURCE_URL_REJECTED, "The audio source has no hostname."
        )
    host = parts.hostname.rstrip(".").lower().encode("idna").decode("ascii")
    if host == "localhost" or host.endswith(".localhost"):
        raise OpenTranscribeError(
            ErrorCode.SOURCE_URL_REJECTED, "Localhost sources are prohibited."
        )
    if allowed_hosts and host not in {item.rstrip(".").lower() for item in allowed_hosts}:
        raise OpenTranscribeError(
            ErrorCode.SOURCE_URL_REJECTED, "The source host is not allow-listed."
        )
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise OpenTranscribeError(
            ErrorCode.SOURCE_URL_REJECTED, "The audio source port is invalid."
        ) from exc
    addresses = await _resolve(host, port)
    if not addresses:
        raise OpenTranscribeError(
            ErrorCode.SOURCE_UNAVAILABLE, "The source hostname has no addresses."
        )
    if not allow_private_urls and any(is_prohibited_ip(value) for value in addresses):
        raise OpenTranscribeError(
            ErrorCode.SOURCE_URL_REJECTED,
            "The source resolves to a prohibited network destination.",
        )
    return ValidatedUrl(
        url=url,
        scheme=parts.scheme,
        host=host,
        port=port,
        resolved_ips=addresses,
    )
