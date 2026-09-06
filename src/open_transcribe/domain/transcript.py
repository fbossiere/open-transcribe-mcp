from typing import Literal

from pydantic import BaseModel, Field

from open_transcribe.domain.audio import ResultMode, TimestampMode, TranscriptStyle
from open_transcribe.domain.errors import ErrorResponse


class TranscriptWord(BaseModel):
    start_ms: int | None = None
    end_ms: int | None = None
    text: str
    confidence: float | None = None


class TranscriptSegment(BaseModel):
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    language: str | None = None
    text: str
    words: list[TranscriptWord] | None = None


class UsageInfo(BaseModel):
    audio_seconds: float | None = None
    estimated_provider_cost_usd: float | None = None


class FallbackAttempt(BaseModel):
    provider: str
    model: str
    reason: str


class TranscriptionMetadata(BaseModel):
    diarization: bool
    timestamps: TimestampMode
    transcript_style: TranscriptStyle
    provider_request_id: str | None = None
    latency_ms: int | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    fallback_history: list[FallbackAttempt] = Field(default_factory=list)


class CanonicalTranscript(BaseModel):
    transcript_id: str
    provider: str
    model: str
    source_duration_ms: int | None = None
    detected_languages: list[str] = Field(default_factory=list)
    text: str | None = None
    segments: list[TranscriptSegment] | None = None
    usage: UsageInfo
    metadata: TranscriptionMetadata
    warnings: list[str] = Field(default_factory=list)


class InlineTranscriptionResult(CanonicalTranscript):
    status: Literal["completed"] = "completed"
    result_mode: Literal[ResultMode.INLINE] = ResultMode.INLINE


class StoredTranscriptionResult(BaseModel):
    status: Literal["completed"] = "completed"
    result_mode: Literal[ResultMode.STORED] = ResultMode.STORED
    transcript_id: str
    provider: str
    model: str
    text_chars: int
    segment_count: int
    warnings: list[str] = Field(default_factory=list)


class TranscriptChunk(BaseModel):
    content: str | list[TranscriptSegment]
    next_cursor: str | None = None
    done: bool


class DeleteResult(BaseModel):
    transcript_id: str
    deleted: bool


class ToolErrorResult(BaseModel):
    status: Literal["error"] = "error"
    error: ErrorResponse


class CostEstimate(BaseModel):
    provider: str
    model: str
    duration_seconds: float
    estimated_cost_usd: float | None
    pricing_valid_at: str | None = None
    warnings: list[str] = Field(default_factory=list)
