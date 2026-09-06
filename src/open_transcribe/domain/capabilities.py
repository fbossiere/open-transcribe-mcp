from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from open_transcribe.domain.audio import TimestampMode, TranscriptStyle


class ModelLifecycle(StrEnum):
    PREVIEW = "preview"
    GA = "ga"
    DEPRECATED = "deprecated"


class PricingDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    billing_unit: Literal["audio_hour"] = "audio_hour"
    price_usd: float
    valid_from: date
    valid_until: date | None = None
    source: str


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    display_name: str
    lifecycle: ModelLifecycle
    languages: list[str] | Literal["dynamic"]
    supports_url_input: bool
    supports_diarization: bool
    timestamp_modes: set[TimestampMode]
    transcript_styles: set[TranscriptStyle]
    supports_language_detection: bool
    supports_code_switching: bool
    supports_phrase_hints: bool
    max_audio_seconds: int | None = None
    max_audio_bytes: int | None = None
    pricing: PricingDescriptor | None = None
    configured: bool = False

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"
