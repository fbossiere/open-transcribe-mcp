from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from open_transcribe.domain.audio import (
    ResolvedAudioSource,
    ResolvedTranscribeRequest,
    TimestampMode,
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
    SpeakerNormalizer,
    normalize_language,
    provider_request_id,
    safe_filename,
)
from open_transcribe.providers.pricing import estimate_from_pricing
from open_transcribe.settings import ElevenLabsSettings


class ElevenLabsProvider(HttpProvider):
    provider_id = "elevenlabs"

    def __init__(
        self,
        settings: ElevenLabsSettings,
        pricing: PricingDescriptor | None,
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
        return [
            ModelDescriptor(
                provider=self.provider_id,
                model="scribe-v2",
                display_name="ElevenLabs Scribe v2",
                lifecycle=ModelLifecycle.GA,
                languages="dynamic",
                supports_url_input=True,
                supports_diarization=True,
                timestamp_modes={TimestampMode.NONE, TimestampMode.SEGMENT, TimestampMode.WORD},
                transcript_styles={"clean", "verbatim"},
                supports_language_detection=True,
                supports_code_switching=True,
                supports_phrase_hints=True,
                max_audio_bytes=5 * 1024 * 1024 * 1024,
                pricing=self.pricing,
                configured=self.configured,
            )
        ]

    async def transcribe(
        self,
        request: ResolvedTranscribeRequest,
        source: ResolvedAudioSource,
        model: ModelDescriptor,
    ) -> CanonicalTranscript:
        if self.settings.api_key is None:
            raise RuntimeError("ElevenLabs provider is not configured")
        api_key = self.settings.api_key.get_secret_value()
        url = f"{str(self.settings.base_url).rstrip('/')}/v1/speech-to-text"
        data: dict[str, Any] = {
            "model_id": "scribe_v2",
            "diarize": str(request.diarization).lower(),
            "timestamps_granularity": (
                "word" if request.timestamps != TimestampMode.NONE else "none"
            ),
            "no_verbatim": str(request.transcript_style.value == "clean").lower(),
        }
        if request.language:
            data["language_code"] = request.language
        if request.speaker_count_hint:
            data["num_speakers"] = str(request.speaker_count_hint)
        if request.phrase_hints:
            data["keyterms"] = request.phrase_hints
        if source.delivery.value == "passthrough":
            data["source_url"] = source.original_url

        async def send() -> httpx.Response:
            files: dict[str, Any] | None = None
            handle = None
            try:
                if source.local_path:
                    handle = Path(source.local_path).open("rb")  # noqa: ASYNC230, SIM115
                    files = {
                        "file": (
                            safe_filename(source.media_type),
                            handle,
                            source.media_type or "application/octet-stream",
                        )
                    }
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds, trust_env=False
                ) as client:
                    return await client.post(
                        url,
                        params={"enable_logging": str(not self.settings.zero_retention).lower()},
                        headers={"xi-api-key": api_key},
                        data=data,
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
        request: ResolvedTranscribeRequest,
        model: ModelDescriptor,
        latency_ms: int,
        request_id: str | None,
    ) -> CanonicalTranscript:
        speakers = SpeakerNormalizer()
        language = normalize_language(data.get("language_code"))
        segments: list[TranscriptSegment] = []
        current: TranscriptSegment | None = None
        for item in data.get("words", []):
            if item.get("type") not in {"word", "spacing"}:
                continue
            speaker = speakers.normalize(item.get("speaker_id")) if request.diarization else None
            start = _seconds_to_ms(item.get("start"))
            end = _seconds_to_ms(item.get("end"))
            if current is None or current.speaker != speaker:
                current = TranscriptSegment(
                    start_ms=start if request.timestamps != TimestampMode.NONE else None,
                    end_ms=end if request.timestamps != TimestampMode.NONE else None,
                    speaker=speaker,
                    language=language,
                    text="",
                    words=[] if request.timestamps == TimestampMode.WORD else None,
                )
                segments.append(current)
            current.text += str(item.get("text", ""))
            if end is not None and request.timestamps != TimestampMode.NONE:
                current.end_ms = end
            if request.timestamps == TimestampMode.WORD and item.get("type") == "word":
                if current.words is None:
                    raise RuntimeError("word collection was not initialized")
                current.words.append(
                    TranscriptWord(
                        start_ms=start,
                        end_ms=end,
                        text=str(item.get("text", "")),
                        confidence=_logprob_to_confidence(item.get("logprob")),
                    )
                )
        text = str(data.get("text", "")).strip()
        duration_ms = max((segment.end_ms or 0 for segment in segments), default=0) or None
        audio_seconds = duration_ms / 1000 if duration_ms is not None else None
        estimate = self.estimate_cost(model.model, audio_seconds) if audio_seconds else None
        return CanonicalTranscript(
            transcript_id=f"tr_{uuid4().hex}",
            provider=self.provider_id,
            model=model.model,
            source_duration_ms=duration_ms,
            detected_languages=[language] if language else [],
            text=text,
            segments=segments,
            usage=UsageInfo(
                audio_seconds=audio_seconds,
                estimated_provider_cost_usd=estimate.estimated_cost_usd if estimate else None,
            ),
            metadata=TranscriptionMetadata(
                diarization=request.diarization,
                timestamps=request.timestamps,
                transcript_style=request.transcript_style,
                provider_request_id=request_id,
                latency_ms=latency_ms,
            ),
        )

    def estimate_cost(self, model: str, duration_seconds: float) -> CostEstimate:
        return estimate_from_pricing(self.provider_id, model, duration_seconds, self.pricing)


def _seconds_to_ms(value: object) -> int | None:
    return round(float(value) * 1000) if isinstance(value, (int, float)) else None


def _logprob_to_confidence(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    import math

    return min(1.0, max(0.0, math.exp(float(value))))
