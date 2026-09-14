"""The optional public sample transcription.

This is a bounded onboarding check, not a feature. The user chooses it explicitly, it uses the
project's own synthetic fixture over the ordinary URL input and the ordinary security checks,
and it is billable like any other request. Setup can be finished without it.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.domain.audio import (
    ProviderId,
    RoutingPolicy,
    TranscribeAudioRequest,
    UrlAudioSource,
)
from open_transcribe.domain.capabilities import ModelDescriptor
from open_transcribe.domain.errors import ErrorCode

SAMPLE_REVISION = "60e045f260a87b9ab5bfabe1c14813436b0275f0"
SAMPLE_URL = (
    "https://raw.githubusercontent.com/fbossiere/open-transcribe-mcp/"
    f"{SAMPLE_REVISION}/tests/fixtures/open-transcribe-bilingual.wav"
)
"""Pinned to an immutable revision, so the bytes the user authorizes cannot change later."""

SAMPLE_SHA256 = "32dd28b8e7c935a0094f9030a0d35531fbd8566d100f1da7b076004636b1e909"
SAMPLE_DURATION_SECONDS = 21.657
SAMPLE_SIZE_BYTES = 955_148
SAMPLE_HOST = "raw.githubusercontent.com"
SAMPLE_DESCRIPTION_KEY = "sample.description"
"""Synthetic, bilingual (English and French), two artificial voices, no real person recorded."""

MAX_DISPLAYED_CHARS = 4000


@dataclass(frozen=True, slots=True)
class SamplePlan:
    """What the user is shown before anything is sent, including what cannot be known."""

    provider: str
    model: str
    duration_seconds: float = SAMPLE_DURATION_SECONDS
    delivery: str = "auto"
    estimated_cost_usd: float | None = None
    pricing_valid_from: str | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    @property
    def cost_is_known(self) -> bool:
        return self.estimated_cost_usd is not None


@dataclass(frozen=True, slots=True)
class SampleResult:
    """A bounded projection of the canonical response, held in memory only."""

    provider: str
    model: str
    language: str | None
    text_preview: str
    truncated: bool
    duration_ms: int | None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def sample_request(model: ModelDescriptor) -> TranscribeAudioRequest:
    """Build the sample request: one fixed model, no fallback, minimum capabilities.

    It goes through the same public input and the same source checks as any other request. There
    is no test-only bypass, and no local filesystem path is introduced anywhere.
    """
    return TranscribeAudioRequest(
        source=UrlAudioSource(url=SAMPLE_URL),  # type: ignore[arg-type]
        provider=ProviderId(model.provider),
        model=model.model,
        routing_policy=RoutingPolicy.FIXED,
        allow_fallback=False,
        strict_capabilities=True,
        duration_seconds_hint=SAMPLE_DURATION_SECONDS,
    )


def capability_request(model: ModelDescriptor) -> TranscribeAudioRequest | None:
    """The optional second check: diarization or word timestamps, where the model supports them."""
    from open_transcribe.domain.audio import TimestampMode

    if model.supports_diarization:
        return sample_request(model).model_copy(update={"diarization": True})
    if TimestampMode.WORD in model.timestamp_modes:
        return sample_request(model).model_copy(update={"timestamps": TimestampMode.WORD})
    return None


def plan_sample(model: ModelDescriptor) -> SamplePlan:
    pricing = model.pricing
    estimate = None
    if pricing is not None:
        estimate = round(pricing.price_usd * SAMPLE_DURATION_SECONDS / 3600, 6)
    capabilities = ["language_detection"] if model.supports_language_detection else []
    return SamplePlan(
        provider=model.provider,
        model=model.model,
        delivery="passthrough" if model.supports_url_input else "relay",
        estimated_cost_usd=estimate,
        pricing_valid_from=pricing.valid_from.isoformat() if pricing else None,
        capabilities=tuple(capabilities),
    )


def summarize(response: dict[str, Any]) -> SampleResult:
    """Project a canonical response into a bounded, inert result. Nothing is persisted."""
    if "error" in response:
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID, "The sample request returned an error response."
        )
    text = str(response.get("text") or "")
    return SampleResult(
        provider=str(response.get("provider", "")),
        model=str(response.get("model", "")),
        language=response.get("language"),
        text_preview=text[:MAX_DISPLAYED_CHARS],
        truncated=len(text) > MAX_DISPLAYED_CHARS,
        duration_ms=response.get("source_duration_ms"),
        warnings=tuple(str(item) for item in response.get("warnings", [])[:20]),
    )


SAMPLE_ERROR_MESSAGE_KEYS: dict[ErrorCode, str] = {
    ErrorCode.PROVIDER_AUTHENTICATION_FAILED: "sample.error.authentication",
    ErrorCode.AUTHENTICATION_FAILED: "sample.error.authentication",
    ErrorCode.UNSUPPORTED_MODEL: "sample.error.model_access",
    ErrorCode.UNSUPPORTED_CAPABILITY: "sample.error.capability",
    ErrorCode.RATE_LIMITED: "sample.error.quota",
    ErrorCode.COST_LIMIT_EXCEEDED: "sample.error.cost",
    ErrorCode.SOURCE_UNAVAILABLE: "sample.error.source",
    ErrorCode.SOURCE_URL_REJECTED: "sample.error.source",
    ErrorCode.PROVIDER_UNAVAILABLE: "sample.error.provider_temporary",
    ErrorCode.PROVIDER_TIMEOUT: "sample.error.provider_temporary",
    ErrorCode.PROVIDER_NOT_ENABLED: "sample.error.not_enabled",
    ErrorCode.TEMPORARY_AUDIO_NOT_PERMITTED: "sample.error.relay_not_permitted",
}


def message_key_for(code: str) -> str:
    """Map a normalized engine error to a distinct sample message. Never a provider's own text."""
    try:
        return SAMPLE_ERROR_MESSAGE_KEYS[ErrorCode(code)]
    except (ValueError, KeyError):
        return "sample.error.unknown"


def fixture_matches(path: Path) -> bool:
    """Confirm the repository fixture still matches the digest the desktop sample publishes."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest() == SAMPLE_SHA256
