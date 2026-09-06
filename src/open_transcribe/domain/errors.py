from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PROVIDER_AUTHENTICATION_FAILED = "PROVIDER_AUTHENTICATION_FAILED"
    SOURCE_URL_REJECTED = "SOURCE_URL_REJECTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_DURATION_EXCEEDED = "SOURCE_DURATION_EXCEEDED"
    INVALID_AUDIO = "INVALID_AUDIO"
    UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    COST_LIMIT_EXCEEDED = "COST_LIMIT_EXCEEDED"
    RESULT_NOT_FOUND = "RESULT_NOT_FOUND"
    RESULT_STORE_DISABLED = "RESULT_STORE_DISABLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    provider: str | None = None
    model: str | None = None
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class OpenTranscribeError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.response = ErrorResponse(
            code=code,
            message=message,
            provider=provider,
            model=model,
            retryable=retryable,
            details=details or {},
        )


class ProviderError(OpenTranscribeError):
    """Normalized provider failure."""
