from enum import StrEnum
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class ProviderId(StrEnum):
    AUTO = "auto"
    MICROSOFT = "microsoft"
    ELEVENLABS = "elevenlabs"
    GROQ = "groq"


class RoutingPolicy(StrEnum):
    DEFAULT = "default"
    QUALITY = "quality"
    COST = "cost"
    LATENCY = "latency"
    FIXED = "fixed"


class TimestampMode(StrEnum):
    NONE = "none"
    SEGMENT = "segment"
    WORD = "word"


class TranscriptStyle(StrEnum):
    CLEAN = "clean"
    VERBATIM = "verbatim"


class SourceDelivery(StrEnum):
    AUTO = "auto"
    PASSTHROUGH = "passthrough"
    PROXY = "proxy"


class ResultMode(StrEnum):
    AUTO = "auto"
    INLINE = "inline"
    STORED = "stored"


class UrlAudioSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["url"] = "url"
    url: AnyHttpUrl


class TranscribeAudioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: UrlAudioSource
    provider: ProviderId = ProviderId.AUTO
    model: str | None = Field(default=None, min_length=1, max_length=128)
    routing_policy: RoutingPolicy = RoutingPolicy.DEFAULT
    language: str | None = Field(default=None, min_length=2, max_length=35)
    diarization: bool = True
    timestamps: TimestampMode = TimestampMode.SEGMENT
    transcript_style: TranscriptStyle = TranscriptStyle.CLEAN
    phrase_hints: list[str] = Field(default_factory=list, max_length=1000)
    speaker_count_hint: int | None = Field(default=None, ge=1, le=32)
    strict_capabilities: bool = True
    allow_fallback: bool = True
    allow_preview_models: bool = True
    source_delivery: SourceDelivery = SourceDelivery.AUTO
    result_mode: ResultMode = ResultMode.AUTO
    duration_seconds_hint: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_routing(self) -> "TranscribeAudioRequest":
        if self.routing_policy == RoutingPolicy.FIXED and self.provider == ProviderId.AUTO:
            raise ValueError("fixed routing requires an explicit provider")
        if self.provider == ProviderId.AUTO and self.model is not None:
            raise ValueError("model requires an explicit provider")
        if any(not value.strip() or len(value) > 50 for value in self.phrase_hints):
            raise ValueError("phrase hints must contain between 1 and 50 characters")
        return self


class ResolvedAudioSource(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    original_url: str
    delivery: SourceDelivery
    local_path: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
