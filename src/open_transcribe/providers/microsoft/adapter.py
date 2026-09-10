import json
from datetime import UTC, datetime
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
from open_transcribe.settings import MicrosoftSettings


class MicrosoftProvider(HttpProvider):
    provider_id = "microsoft"

    def __init__(
        self,
        settings: MicrosoftSettings,
        pricing: PricingDescriptor | None,
        *,
        timeout_seconds: int,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self.settings = settings
        self.pricing = pricing

    @property
    def configured(self) -> bool:
        return self.settings.endpoint is not None and self.settings.api_key is not None

    def list_models(self) -> list[ModelDescriptor]:
        return [
            ModelDescriptor(
                provider=self.provider_id,
                model="MAI-Transcribe-2",
                display_name="Microsoft MAI-Transcribe-2",
                lifecycle=ModelLifecycle.PREVIEW,
                languages="dynamic",
                supports_url_input=True,
                supports_diarization=True,
                timestamp_modes={TimestampMode.NONE, TimestampMode.SEGMENT, TimestampMode.WORD},
                transcript_styles={"clean", "verbatim"},
                supports_language_detection=True,
                supports_code_switching=True,
                supports_phrase_hints=True,
                max_audio_seconds=18000,
                max_audio_bytes=500 * 1024 * 1024,
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
        if self.settings.endpoint is None or self.settings.api_key is None:
            raise RuntimeError("Microsoft provider is not configured")
        endpoint = str(self.settings.endpoint).rstrip("/")
        api_key = self.settings.api_key.get_secret_value()
        url = f"{endpoint}/speechtotext/transcriptions:transcribe"
        definition: dict[str, Any] = {
            "enhancedMode": {
                "enabled": True,
                "model": model.model,
                "modelOptions": {"transcribeStyle": request.transcript_style.value},
            }
        }
        if request.timestamps == TimestampMode.WORD:
            definition["enhancedMode"]["modelOptions"]["timestamps"] = "word"
        if request.diarization:
            definition["diarization"] = {"enabled": True}
            if request.speaker_count_hint:
                definition["diarization"]["maxSpeakers"] = request.speaker_count_hint
        if request.language:
            definition["locales"] = [request.language]
        if request.phrase_hints:
            definition["phraseList"] = {"phrases": request.phrase_hints}
        if source.delivery.value == "passthrough":
            definition["audioUrl"] = source.original_url

        async def send() -> httpx.Response:
            files: dict[str, Any] = {
                "definition": (None, json.dumps(definition), "application/json")
            }
            handle = None
            try:
                if source.local_path:
                    handle = Path(source.local_path).open("rb")  # noqa: ASYNC230, SIM115
                    files["audio"] = (
                        safe_filename(source.media_type),
                        handle,
                        source.media_type or "application/octet-stream",
                    )
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds, trust_env=False
                ) as client:
                    return await client.post(
                        url,
                        params={"api-version": self.settings.api_version},
                        headers={"Ocp-Apim-Subscription-Key": api_key},
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
        segments: list[TranscriptSegment] = []
        languages: list[str] = []
        for phrase in data.get("phrases", []):
            language = normalize_language(phrase.get("locale"))
            if language and language not in languages:
                languages.append(language)
            words = None
            if request.timestamps == TimestampMode.WORD:
                words = [
                    TranscriptWord(
                        start_ms=word.get("offsetMilliseconds"),
                        end_ms=(
                            word.get("offsetMilliseconds", 0) + word.get("durationMilliseconds", 0)
                        ),
                        text=str(word.get("text", "")),
                        confidence=word.get("confidence"),
                    )
                    for word in phrase.get("words", [])
                ]
            start = phrase.get("offsetMilliseconds")
            duration = phrase.get("durationMilliseconds")
            segments.append(
                TranscriptSegment(
                    start_ms=start if request.timestamps != TimestampMode.NONE else None,
                    end_ms=(start + duration)
                    if start is not None
                    and duration is not None
                    and request.timestamps != TimestampMode.NONE
                    else None,
                    speaker=speakers.normalize(phrase.get("speaker"))
                    if request.diarization
                    else None,
                    language=language,
                    text=str(phrase.get("text", "")),
                    words=words,
                )
            )
        combined = data.get("combinedPhrases", [])
        text = "\n".join(str(item.get("text", "")) for item in combined).strip()
        if not text:
            text = " ".join(segment.text for segment in segments).strip()
        duration_ms = data.get("durationMilliseconds")
        audio_seconds = duration_ms / 1000 if isinstance(duration_ms, (int, float)) else None
        estimate = self.estimate_cost(model.model, audio_seconds) if audio_seconds else None
        return CanonicalTranscript(
            transcript_id=f"tr_{uuid4().hex}",
            provider=self.provider_id,
            model=model.model,
            source_duration_ms=duration_ms,
            detected_languages=languages,
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
        cost = duration_seconds / 3600 * self.pricing.price_usd if self.pricing else None
        warnings = [] if self.pricing else ["pricing_metadata_unavailable"]
        if (
            self.pricing
            and self.pricing.valid_until
            and self.pricing.valid_until < datetime.now(UTC).date()
        ):
            warnings.append("pricing_metadata_expired")
        return CostEstimate(
            provider=self.provider_id,
            model=model,
            duration_seconds=duration_seconds,
            estimated_cost_usd=round(cost, 6) if cost is not None else None,
            pricing_valid_at=str(self.pricing.valid_from) if self.pricing else None,
            warnings=warnings,
        )
