from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from open_transcribe.domain.audio import (
    ResolvedAudioSource,
    SourceDelivery,
    TimestampMode,
    TranscribeAudioRequest,
)
from open_transcribe.domain.capabilities import ModelDescriptor, ModelLifecycle, PricingDescriptor
from open_transcribe.domain.transcript import (
    CanonicalTranscript,
    CostEstimate,
    TranscriptionMetadata,
    TranscriptSegment,
    TranscriptWord,
    UsageInfo,
)
from open_transcribe.providers.base import HttpProvider
from open_transcribe.providers.normalization import (
    normalize_language,
    provider_request_id,
    safe_filename,
)
from open_transcribe.providers.pricing import estimate_from_pricing
from open_transcribe.settings import GroqSettings


class GroqProvider(HttpProvider):
    provider_id = "groq"

    def __init__(
        self,
        settings: GroqSettings,
        pricing: dict[str, PricingDescriptor | None],
        *,
        timeout_seconds: int,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self.settings = settings
        self.pricing = pricing

    @property
    def configured(self) -> bool:
        return self.settings.api_key is not None

    def list_models(self) -> list[ModelDescriptor]:
        return [self._descriptor(name) for name in ("whisper-large-v3", "whisper-large-v3-turbo")]

    def _descriptor(self, model: str) -> ModelDescriptor:
        return ModelDescriptor(
            provider=self.provider_id,
            model=model,
            display_name=f"Groq {model}",
            lifecycle=ModelLifecycle.GA,
            languages="dynamic",
            supports_url_input=True,
            supports_diarization=False,
            timestamp_modes={TimestampMode.NONE, TimestampMode.SEGMENT, TimestampMode.WORD},
            transcript_styles={"verbatim"},
            supports_language_detection=True,
            supports_code_switching=False,
            supports_phrase_hints=True,
            max_audio_seconds=28800,
            max_audio_bytes=100 * 1024 * 1024,
            pricing=self.pricing.get(model),
            configured=self.configured,
        )

    async def transcribe(
        self,
        request: TranscribeAudioRequest,
        source: ResolvedAudioSource,
        model: ModelDescriptor,
    ) -> CanonicalTranscript:
        if self.settings.api_key is None:
            raise RuntimeError("Groq provider is not configured")
        if source.local_path is None and source.delivery != SourceDelivery.PASSTHROUGH:
            raise RuntimeError("Groq provider has no usable audio source")
        api_key = self.settings.api_key.get_secret_value()
        local_path = source.local_path
        url = f"{str(self.settings.base_url).rstrip('/')}/audio/transcriptions"
        data: dict[str, Any] = {"model": model.model, "response_format": "verbose_json"}
        if request.language:
            data["language"] = request.language
        if request.phrase_hints:
            data["prompt"] = ", ".join(request.phrase_hints)
        if request.timestamps == TimestampMode.WORD:
            data["timestamp_granularities[]"] = ["word", "segment"]
        elif request.timestamps == TimestampMode.SEGMENT:
            data["timestamp_granularities[]"] = "segment"
        if source.delivery == SourceDelivery.PASSTHROUGH:
            data["url"] = source.original_url

        async def send() -> httpx.Response:
            handle = (
                Path(local_path).open("rb") if local_path else None  # noqa: ASYNC230, SIM115
            )
            try:
                files: list[tuple[str, Any]] = []
                for name, value in data.items():
                    values = value if isinstance(value, list) else [value]
                    files.extend((name, (None, str(item))) for item in values)
                if handle:
                    files.append(
                        (
                            "file",
                            (
                                safe_filename(source.media_type),
                                handle,
                                source.media_type or "application/octet-stream",
                            ),
                        )
                    )
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds, trust_env=False
                ) as client:
                    return await client.post(
                        url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        files=files,
                    )
            finally:
                if handle:
                    handle.close()

        response, latency_ms = await self._request_with_retry(
            send, provider=self.provider_id, model=model.model
        )
        return self.normalize(
            self.parse_json(response, provider=self.provider_id, model=model.model),
            request=request,
            model=model,
            latency_ms=latency_ms,
            request_id=provider_request_id(response.headers),
        )

    def normalize(
        self,
        data: dict[str, Any],
        *,
        request: TranscribeAudioRequest,
        model: ModelDescriptor,
        latency_ms: int,
        request_id: str | None,
    ) -> CanonicalTranscript:
        language = normalize_language(data.get("language"))
        raw_words = data.get("words", [])
        segments = [
            TranscriptSegment(
                start_ms=_seconds_to_ms(item.get("start"))
                if request.timestamps != TimestampMode.NONE
                else None,
                end_ms=_seconds_to_ms(item.get("end"))
                if request.timestamps != TimestampMode.NONE
                else None,
                language=language,
                text=str(item.get("text", "")).strip(),
                words=_words_for_segment(raw_words, item)
                if request.timestamps == TimestampMode.WORD
                else None,
            )
            for item in data.get("segments", [])
        ]
        duration = data.get("duration")
        duration_ms = _seconds_to_ms(duration)
        if duration_ms is None:
            duration_ms = max((segment.end_ms or 0 for segment in segments), default=0) or None
        audio_seconds = duration_ms / 1000 if duration_ms else None
        estimate = self.estimate_cost(model.model, audio_seconds) if audio_seconds else None
        return CanonicalTranscript(
            transcript_id=f"tr_{uuid4().hex}",
            provider=self.provider_id,
            model=model.model,
            source_duration_ms=duration_ms,
            detected_languages=[language] if language else [],
            text=str(data.get("text", "")).strip(),
            segments=segments,
            usage=UsageInfo(
                audio_seconds=audio_seconds,
                estimated_provider_cost_usd=estimate.estimated_cost_usd if estimate else None,
            ),
            metadata=TranscriptionMetadata(
                diarization=False,
                timestamps=request.timestamps,
                transcript_style=request.transcript_style,
                provider_request_id=request_id,
                latency_ms=latency_ms,
            ),
        )

    def estimate_cost(self, model: str, duration_seconds: float) -> CostEstimate:
        return estimate_from_pricing(
            self.provider_id, model, duration_seconds, self.pricing.get(model)
        )


def _seconds_to_ms(value: object) -> int | None:
    return round(float(value) * 1000) if isinstance(value, (int, float)) else None


def _words_for_segment(
    words: list[dict[str, Any]], segment: dict[str, Any]
) -> list[TranscriptWord]:
    start = float(segment.get("start", 0))
    end = float(segment.get("end", float("inf")))
    return [
        TranscriptWord(
            start_ms=_seconds_to_ms(word.get("start")),
            end_ms=_seconds_to_ms(word.get("end")),
            text=str(word.get("word", word.get("text", ""))).strip(),
            confidence=word.get("confidence"),
        )
        for word in words
        if isinstance(word.get("start"), (int, float)) and start <= float(word["start"]) <= end
    ]
