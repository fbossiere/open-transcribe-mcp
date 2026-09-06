import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urljoin

import httpx

from open_transcribe.domain.audio import ResolvedAudioSource, SourceDelivery
from open_transcribe.domain.capabilities import ModelDescriptor
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.security.redaction import redact_url
from open_transcribe.security.ssrf import ValidatedUrl, validate_source_url
from open_transcribe.settings import Settings


class SourceBroker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def select_delivery(self, requested: SourceDelivery, model: ModelDescriptor) -> SourceDelivery:
        if requested == SourceDelivery.PASSTHROUGH and not model.supports_url_input:
            raise OpenTranscribeError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "The selected model does not support URL passthrough.",
                provider=model.provider,
                model=model.model,
            )
        if requested == SourceDelivery.AUTO:
            return SourceDelivery.PASSTHROUGH if model.supports_url_input else SourceDelivery.PROXY
        return requested

    @asynccontextmanager
    async def resolve(
        self, source_url: str, requested: SourceDelivery, model: ModelDescriptor
    ) -> AsyncIterator[ResolvedAudioSource]:
        security = self.settings.security
        validated = await validate_source_url(
            source_url,
            require_https=security.require_https_sources,
            allow_private_urls=security.allow_private_urls,
            allowed_hosts=security.allowed_source_hosts,
        )
        delivery = self.select_delivery(requested, model)
        if delivery == SourceDelivery.PASSTHROUGH:
            yield ResolvedAudioSource(original_url=source_url, delivery=delivery)
            return
        path: str | None = None
        try:
            path, media_type, size = await self._download(source_url, validated)
            yield ResolvedAudioSource(
                original_url=source_url,
                delivery=delivery,
                local_path=path,
                media_type=media_type,
                size_bytes=size,
            )
        finally:
            if path:
                await asyncio.to_thread(Path(path).unlink, missing_ok=True)

    async def _download(
        self, source_url: str, validated: ValidatedUrl
    ) -> tuple[str, str | None, int]:
        current = source_url
        with tempfile.NamedTemporaryFile(prefix="open-transcribe-", delete=False) as temp:
            path = temp.name
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                limits=httpx.Limits(max_keepalive_connections=0),
                timeout=self.settings.source_download_timeout_seconds,
                trust_env=False,
            ) as client:
                for redirect_count in range(self.settings.security.max_redirects + 1):
                    target_url, host_header = validated.connection_target(validated.resolved_ips[0])
                    try:
                        async with client.stream(
                            "GET",
                            target_url,
                            headers={"Host": host_header},
                            extensions={"sni_hostname": validated.host},
                        ) as response:
                            if response.is_redirect:
                                location = response.headers.get("location")
                                if (
                                    not location
                                    or redirect_count >= self.settings.security.max_redirects
                                ):
                                    raise OpenTranscribeError(
                                        ErrorCode.SOURCE_URL_REJECTED,
                                        "The source redirect chain is invalid or too long.",
                                    )
                                current = urljoin(current, location)
                                validated = await validate_source_url(
                                    current,
                                    require_https=self.settings.security.require_https_sources,
                                    allow_private_urls=self.settings.security.allow_private_urls,
                                    allowed_hosts=self.settings.security.allowed_source_hosts,
                                )
                                continue
                            if response.status_code >= 400:
                                raise OpenTranscribeError(
                                    ErrorCode.SOURCE_UNAVAILABLE,
                                    "The audio source could not be downloaded.",
                                    details={"status_code": response.status_code},
                                )
                            length = response.headers.get("content-length")
                            if length:
                                try:
                                    declared_size = int(length)
                                except ValueError as exc:
                                    raise OpenTranscribeError(
                                        ErrorCode.SOURCE_UNAVAILABLE,
                                        "The audio source returned an invalid content length.",
                                    ) from exc
                                if declared_size < 0:
                                    raise OpenTranscribeError(
                                        ErrorCode.SOURCE_UNAVAILABLE,
                                        "The audio source returned an invalid content length.",
                                    )
                                if declared_size > self.settings.max_audio_bytes:
                                    raise OpenTranscribeError(
                                        ErrorCode.SOURCE_TOO_LARGE,
                                        "The audio source exceeds the configured size limit.",
                                    )
                            media_type = response.headers.get("content-type")
                            size = 0
                            prefix = b""
                            with open(path, "wb") as handle:  # noqa: ASYNC230
                                async for chunk in response.aiter_bytes(64 * 1024):
                                    size += len(chunk)
                                    if size > self.settings.max_audio_bytes:
                                        raise OpenTranscribeError(
                                            ErrorCode.SOURCE_TOO_LARGE,
                                            "The audio source exceeds the configured size limit.",
                                        )
                                    if len(prefix) < 16:
                                        prefix += chunk[: 16 - len(prefix)]
                                    handle.write(chunk)
                            self._validate_audio(prefix, media_type, size)
                            return path, media_type, size
                    except (httpx.TimeoutException, httpx.NetworkError) as exc:
                        raise OpenTranscribeError(
                            ErrorCode.SOURCE_UNAVAILABLE,
                            f"The audio source at {redact_url(current)} could not be downloaded.",
                            retryable=True,
                        ) from exc
        except Exception:
            await asyncio.to_thread(Path(path).unlink, missing_ok=True)
            raise
        raise OpenTranscribeError(ErrorCode.SOURCE_URL_REJECTED, "The redirect limit was exceeded.")

    @staticmethod
    def _validate_audio(prefix: bytes, media_type: str | None, size: int) -> None:
        if size == 0:
            raise OpenTranscribeError(ErrorCode.INVALID_AUDIO, "The audio source is empty.")
        normalized_type = (media_type or "").split(";", 1)[0].strip().lower()
        type_ok = normalized_type.startswith(("audio/", "video/")) or normalized_type in {
            "application/octet-stream",
            "binary/octet-stream",
            "",
        }
        magic_ok = (
            prefix.startswith((b"ID3", b"RIFF", b"OggS", b"fLaC", b"\x1aE\xdf\xa3"))
            or (len(prefix) >= 8 and prefix[4:8] == b"ftyp")
            or prefix[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}
        )
        if not type_ok or (normalized_type in {"", "application/octet-stream"} and not magic_ok):
            raise OpenTranscribeError(
                ErrorCode.INVALID_AUDIO, "The source does not appear to contain supported audio."
            )
