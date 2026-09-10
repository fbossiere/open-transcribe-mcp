from typing import Literal

from open_transcribe.domain.audio import ResultMode, TranscribeAudioRequest
from open_transcribe.domain.capabilities import ModelDescriptor
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError, ProviderError
from open_transcribe.domain.transcript import (
    CanonicalTranscript,
    CostEstimate,
    DeleteResult,
    FallbackAttempt,
    InlineTranscriptionResult,
    StoredTranscriptionResult,
    TranscriptChunk,
)
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.result_store.base import ResultStore
from open_transcribe.routing.router import RouteCandidate, Router
from open_transcribe.settings import Settings
from open_transcribe.sources.resolver import SourceBroker


class TranscriptionService:
    def __init__(
        self,
        settings: Settings,
        registry: ProviderRegistry,
        router: Router,
        source_broker: SourceBroker,
        result_store: ResultStore,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.router = router
        self.source_broker = source_broker
        self.result_store = result_store

    async def transcribe(
        self, request: TranscribeAudioRequest
    ) -> InlineTranscriptionResult | StoredTranscriptionResult:
        candidates = self.router.route(request)
        self._enforce_preflight_limits(request, candidates[0].model)
        failures: list[FallbackAttempt] = []
        transcript = None
        selected: RouteCandidate | None = None
        for candidate in candidates:
            provider = self.registry.get_provider(candidate.model.provider)
            # Capabilities are bound per candidate, so a fallback model is asked for what it can
            # actually do rather than for whatever the first candidate supported.
            resolved = candidate.request
            try:
                async with self.source_broker.resolve(
                    str(resolved.source.url), resolved.source_delivery, candidate.model
                ) as source:
                    if (
                        source.size_bytes
                        and candidate.model.max_audio_bytes
                        and source.size_bytes > candidate.model.max_audio_bytes
                    ):
                        raise OpenTranscribeError(
                            ErrorCode.SOURCE_TOO_LARGE,
                            "The source exceeds the selected model's size limit.",
                            provider=candidate.model.provider,
                            model=candidate.model.model,
                        )
                    transcript = await provider.transcribe(resolved, source, candidate.model)
                    selected = candidate
                    break
            except ProviderError as exc:
                if not exc.response.retryable or not request.allow_fallback:
                    raise
                failures.append(
                    FallbackAttempt(
                        provider=candidate.model.provider,
                        model=candidate.model.model,
                        reason=str(exc.response.details.get("reason", exc.response.code.value)),
                    )
                )
        if transcript is None or selected is None:
            raise OpenTranscribeError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "All compatible transcription providers failed.",
                retryable=True,
                details={"attempts": [item.model_dump() for item in failures]},
            )
        transcript.warnings.extend(selected.warnings)
        if failures:
            transcript.metadata.fallback_used = True
            transcript.metadata.fallback_reason = failures[-1].reason
            transcript.metadata.fallback_history = failures
        if (
            transcript.source_duration_ms
            and transcript.source_duration_ms / 1000 > self.settings.max_audio_duration_seconds
        ):
            raise OpenTranscribeError(
                ErrorCode.SOURCE_DURATION_EXCEEDED,
                "The audio exceeds the configured duration limit.",
            )
        return await self._format_result(request.result_mode, transcript)

    def _enforce_preflight_limits(
        self, request: TranscribeAudioRequest, model: ModelDescriptor
    ) -> None:
        if request.duration_seconds_hint is None:
            return
        if request.duration_seconds_hint > self.settings.max_audio_duration_seconds:
            raise OpenTranscribeError(
                ErrorCode.SOURCE_DURATION_EXCEEDED,
                "The duration hint exceeds the configured limit.",
            )
        if self.settings.max_request_cost_usd is None:
            return
        estimate = self.registry.get_provider(model.provider).estimate_cost(
            model.model, request.duration_seconds_hint
        )
        if estimate.estimated_cost_usd is None:
            raise OpenTranscribeError(
                ErrorCode.COST_LIMIT_EXCEEDED,
                "Pricing metadata is required to enforce the configured cost ceiling.",
            )
        if estimate.estimated_cost_usd > self.settings.max_request_cost_usd:
            raise OpenTranscribeError(
                ErrorCode.COST_LIMIT_EXCEEDED,
                "The estimated transcription cost exceeds the configured limit.",
                details={"estimated_cost_usd": estimate.estimated_cost_usd},
            )

    async def _format_result(
        self, requested: ResultMode, transcript: CanonicalTranscript
    ) -> InlineTranscriptionResult | StoredTranscriptionResult:
        serialized_size = len(transcript.model_dump_json().encode())
        too_large = (
            len(transcript.text or "") > self.settings.max_inline_text_chars
            or len(transcript.segments or []) > self.settings.max_inline_segments
            or serialized_size > self.settings.max_inline_response_bytes
        )
        should_store = requested == ResultMode.STORED or (
            requested == ResultMode.AUTO and too_large
        )
        if (
            requested == ResultMode.INLINE
            and serialized_size > self.settings.max_inline_response_bytes
        ):
            raise OpenTranscribeError(
                ErrorCode.RESULT_STORE_DISABLED,
                "The transcript exceeds the hard inline response limit; use stored mode.",
            )
        if should_store:
            await self.result_store.put(transcript)
            return StoredTranscriptionResult(
                transcript_id=transcript.transcript_id,
                provider=transcript.provider,
                model=transcript.model,
                text_chars=len(transcript.text or ""),
                segment_count=len(transcript.segments or []),
                warnings=transcript.warnings,
            )
        return InlineTranscriptionResult.model_validate(
            {**transcript.model_dump(mode="python"), "status": "completed", "result_mode": "inline"}
        )

    def list_models(self, *, configured_only: bool = False) -> list[ModelDescriptor]:
        models = self.registry.list_models()
        return [model for model in models if model.configured or not configured_only]

    def estimate_cost(self, duration_seconds: float, provider: str, model: str) -> CostEstimate:
        if duration_seconds <= 0 or duration_seconds > self.settings.max_audio_duration_seconds:
            raise OpenTranscribeError(
                ErrorCode.SOURCE_DURATION_EXCEEDED, "duration_seconds is outside configured limits."
            )
        descriptor = self.registry.get_model(provider, model)
        return self.registry.get_provider(provider).estimate_cost(
            descriptor.model, duration_seconds
        )

    async def get_chunk(
        self,
        transcript_id: str,
        cursor: str | None,
        max_chars: int,
        format: Literal["text", "segments"],
    ) -> TranscriptChunk:
        return await self.result_store.get_chunk(transcript_id, cursor, max_chars, format)

    async def delete(self, transcript_id: str) -> DeleteResult:
        return await self.result_store.delete(transcript_id)
