from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

import httpx
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from open_transcribe.domain.audio import ResolvedAudioSource, TranscribeAudioRequest
from open_transcribe.domain.capabilities import ModelDescriptor
from open_transcribe.domain.errors import ErrorCode, ProviderError
from open_transcribe.domain.transcript import CanonicalTranscript, CostEstimate

_BACKOFF = wait_random_exponential(multiplier=0.25, max=4)

_TRANSIENT_OUTCOMES: dict[str, tuple[ErrorCode, str]] = {
    "provider_timeout": (
        ErrorCode.PROVIDER_TIMEOUT,
        "The transcription provider did not respond in time.",
    ),
    "provider_http_429": (
        ErrorCode.RATE_LIMITED,
        "The transcription provider rate limit was exceeded.",
    ),
}
_TRANSIENT_FALLBACK = (
    ErrorCode.PROVIDER_UNAVAILABLE,
    "The transcription provider is temporarily unavailable.",
)


class TransientRequestError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TranscriptionProvider(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def list_models(self) -> list[ModelDescriptor]: ...

    @abstractmethod
    async def transcribe(
        self,
        request: TranscribeAudioRequest,
        source: ResolvedAudioSource,
        model: ModelDescriptor,
    ) -> CanonicalTranscript: ...

    @abstractmethod
    def estimate_cost(self, model: str, duration_seconds: float) -> CostEstimate: ...


class HttpProvider(TranscriptionProvider):
    def __init__(self, *, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds

    async def _request_with_retry(
        self,
        send: Callable[[], Awaitable[httpx.Response]],
        *,
        provider: str,
        model: str,
    ) -> tuple[httpx.Response, int]:
        started = monotonic()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=_BACKOFF,
                retry=retry_if_exception_type(TransientRequestError),
                reraise=True,
            ):
                with attempt:
                    try:
                        response = await send()
                    except httpx.TimeoutException as exc:
                        raise TransientRequestError("provider_timeout") from exc
                    except httpx.NetworkError as exc:
                        raise TransientRequestError("provider_network_failure") from exc
                    if response.status_code == 429 or response.status_code >= 500:
                        await response.aclose()
                        self._raise_transient(f"provider_http_{response.status_code}")
                    self._raise_for_status(response, provider=provider, model=model)
                    return response, int((monotonic() - started) * 1000)
        except TransientRequestError as exc:
            code, message = _TRANSIENT_OUTCOMES.get(exc.reason, _TRANSIENT_FALLBACK)
            raise ProviderError(
                code,
                message,
                provider=provider,
                model=model,
                retryable=True,
                details={"reason": exc.reason},
            ) from exc
        raise AssertionError("retry loop returned no result")

    @staticmethod
    def _raise_transient(reason: str) -> None:
        raise TransientRequestError(reason)

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, provider: str, model: str) -> None:
        if response.status_code < 400:
            return
        if response.status_code in {401, 403}:
            code = ErrorCode.PROVIDER_AUTHENTICATION_FAILED
            message = "The transcription provider rejected its configured credentials."
        elif response.status_code == 429:
            code = ErrorCode.RATE_LIMITED
            message = "The transcription provider rate limit was exceeded."
        elif response.status_code in {400, 404, 409, 413, 415, 422}:
            code = ErrorCode.INVALID_AUDIO
            message = "The provider rejected the audio or transcription parameters."
        else:
            code = ErrorCode.PROVIDER_UNAVAILABLE
            message = "The transcription provider returned an error."
        raise ProviderError(
            code,
            message,
            provider=provider,
            model=model,
            retryable=response.status_code == 429 or response.status_code >= 500,
            details={"status_code": response.status_code},
        )

    @staticmethod
    def parse_json(response: httpx.Response, *, provider: str, model: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                ErrorCode.PROVIDER_RESPONSE_INVALID,
                "The provider returned invalid JSON.",
                provider=provider,
                model=model,
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                ErrorCode.PROVIDER_RESPONSE_INVALID,
                "The provider returned an unexpected response shape.",
                provider=provider,
                model=model,
            )
        return data


def safe_validate_transcript(
    data: dict[str, Any], *, provider: str, model: str
) -> CanonicalTranscript:
    try:
        return CanonicalTranscript.model_validate(data)
    except ValidationError as exc:
        raise ProviderError(
            ErrorCode.PROVIDER_RESPONSE_INVALID,
            "The provider response could not be normalized.",
            provider=provider,
            model=model,
        ) from exc
