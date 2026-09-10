from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from open_transcribe.domain.audio import (
    ProviderId,
    ResolvedTranscribeRequest,
    RoutingPolicy,
    TimestampMode,
    TranscribeAudioRequest,
    TranscriptStyle,
)
from open_transcribe.domain.capabilities import ModelDescriptor, ModelLifecycle
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.settings import Settings

TIMESTAMP_PREFERENCE = (TimestampMode.SEGMENT, TimestampMode.WORD, TimestampMode.NONE)
STYLE_PREFERENCE = (TranscriptStyle.CLEAN, TranscriptStyle.VERBATIM)


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    model: ModelDescriptor
    request: ResolvedTranscribeRequest
    warnings: tuple[str, ...] = field(default_factory=tuple)


class Router:
    def __init__(
        self,
        registry: ProviderRegistry,
        settings: Settings,
        routing_config: dict[str, Any] | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings
        self.config = routing_config or load_routing(settings.config_dir / "routing.yaml")

    def route(self, request: TranscribeAudioRequest) -> list[RouteCandidate]:
        models = [model for model in self.registry.list_models() if model.configured]
        if not models:
            raise OpenTranscribeError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "No transcription provider is configured.",
            )
        explicit: ModelDescriptor | None = None
        if request.provider != ProviderId.AUTO:
            provider_models = [
                model for model in models if model.provider == request.provider.value
            ]
            if not provider_models:
                self.registry.get_provider(request.provider.value)
                raise OpenTranscribeError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"Provider {request.provider.value} is not configured.",
                    provider=request.provider.value,
                )
            explicit = (
                self.registry.get_model(request.provider.value, request.model)
                if request.model
                else provider_models[0]
            )
            models = [explicit, *[model for model in models if model.key != explicit.key]]

        evaluated = [(model, self._missing_capabilities(request, model)) for model in models]
        compatible = [
            self._candidate(request, model, []) for model, missing in evaluated if not missing
        ]
        if explicit and (missing := self._missing_capabilities(request, explicit)):
            if request.strict_capabilities:
                raise OpenTranscribeError(
                    ErrorCode.UNSUPPORTED_CAPABILITY,
                    f"{explicit.key} does not support: {', '.join(missing)}.",
                    provider=explicit.provider,
                    model=explicit.model,
                    details={"unsupported": missing},
                )
            compatible.insert(0, self._candidate(request, explicit, missing))
        if not compatible and not request.strict_capabilities:
            # No model satisfies the request, but the caller allowed a downgrade. Offer every
            # configured model with the capabilities it cannot honour dropped and reported,
            # rather than making the flag meaningless whenever the provider is not named.
            compatible = [self._candidate(request, model, missing) for model, missing in evaluated]
        if not compatible:
            requested = sorted({name for _, missing in evaluated for name in missing})
            raise OpenTranscribeError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "No configured model satisfies the requested capabilities.",
                details={"unsatisfied": requested},
            )

        ordered = self._order(request.routing_policy, compatible, explicit)
        if explicit and ordered[0].model.key != explicit.key:
            ordered.sort(key=lambda candidate: candidate.model.key != explicit.key)
        if not request.allow_fallback:
            return ordered[:1]
        return ordered

    def _candidate(
        self, request: TranscribeAudioRequest, model: ModelDescriptor, missing: list[str]
    ) -> RouteCandidate:
        return RouteCandidate(
            model,
            self._resolve(request, model),
            tuple(f"requested_capability_not_supported:{name}" for name in missing),
        )

    def _resolve(
        self, request: TranscribeAudioRequest, model: ModelDescriptor
    ) -> ResolvedTranscribeRequest:
        """Bind the capabilities the caller left unstated to what the selected model supports.

        A stated capability the model cannot honour only reaches this point when the caller
        allowed a downgrade, and its candidate carries a warning naming it. Providers therefore
        never receive a capability their model would silently ignore.
        """
        timestamps = request.timestamps
        if timestamps not in model.timestamp_modes:
            timestamps = next(
                (mode for mode in TIMESTAMP_PREFERENCE if mode in model.timestamp_modes),
                TimestampMode.NONE,
            )
        style = request.transcript_style
        if style not in model.transcript_styles:
            style = next(
                (
                    candidate
                    for candidate in STYLE_PREFERENCE
                    if candidate in model.transcript_styles
                ),
                TranscriptStyle.VERBATIM,
            )
        diarization = (
            model.supports_diarization if request.diarization is None else request.diarization
        )
        return ResolvedTranscribeRequest.model_validate(
            {
                **request.model_dump(mode="python"),
                "diarization": diarization and model.supports_diarization,
                "timestamps": timestamps,
                "transcript_style": style,
            }
        )

    def _missing_capabilities(
        self, request: TranscribeAudioRequest, model: ModelDescriptor
    ) -> list[str]:
        missing: list[str] = []
        if model.lifecycle == ModelLifecycle.PREVIEW and not request.allow_preview_models:
            missing.append("preview_model")
        if request.diarization and not model.supports_diarization:
            missing.append("diarization")
        if request.timestamps is not None and request.timestamps not in model.timestamp_modes:
            missing.append(f"timestamps:{request.timestamps.value}")
        if request.transcript_style is not None and (
            request.transcript_style not in model.transcript_styles
        ):
            missing.append(f"transcript_style:{request.transcript_style.value}")
        if request.language is None and not model.supports_language_detection:
            missing.append("language_detection")
        if request.phrase_hints and not model.supports_phrase_hints:
            missing.append("phrase_hints")
        if (
            request.duration_seconds_hint
            and model.max_audio_seconds
            and request.duration_seconds_hint > model.max_audio_seconds
        ):
            missing.append("max_audio_seconds")
        return missing

    def _order(
        self,
        policy: RoutingPolicy,
        candidates: list[RouteCandidate],
        explicit: ModelDescriptor | None,
    ) -> list[RouteCandidate]:
        if policy == RoutingPolicy.FIXED:
            return candidates[:1]
        if policy == RoutingPolicy.COST:
            return sorted(
                candidates,
                key=lambda candidate: (
                    candidate.model.pricing is None,
                    candidate.model.pricing.price_usd if candidate.model.pricing else float("inf"),
                    candidate.model.key,
                ),
            )
        if policy in {RoutingPolicy.QUALITY, RoutingPolicy.LATENCY}:
            ranking = self.config.get("policies", {}).get(policy.value, [])
            positions = {key: index for index, key in enumerate(ranking)}
            return sorted(
                candidates,
                key=lambda candidate: (
                    positions.get(candidate.model.key, 10_000),
                    candidate.model.key,
                ),
            )
        default_key = f"{self.settings.default_provider}/{self.settings.default_model}"
        return sorted(
            candidates,
            key=lambda candidate: (
                0 if explicit and candidate.model.key == explicit.key else 1,
                0 if candidate.model.key == default_key else 1,
                candidate.model.key,
            ),
        )


def load_routing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
