from pathlib import Path
from typing import Any

import yaml

from open_transcribe.domain.capabilities import ModelDescriptor, PricingDescriptor
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.providers.base import TranscriptionProvider
from open_transcribe.providers.elevenlabs.adapter import ElevenLabsProvider
from open_transcribe.providers.groq.adapter import GroqProvider
from open_transcribe.providers.microsoft.adapter import MicrosoftProvider
from open_transcribe.settings import Settings


class ProviderRegistry:
    def __init__(self, providers: list[TranscriptionProvider]) -> None:
        self.providers = {provider.provider_id: provider for provider in providers}
        self.models = {
            descriptor.key: descriptor
            for provider in providers
            for descriptor in provider.list_models()
        }

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProviderRegistry":
        pricing = load_pricing(settings.config_dir / "pricing.yaml")
        return cls(
            [
                MicrosoftProvider(
                    settings.microsoft,
                    pricing.get("microsoft", {}).get("MAI-Transcribe-2"),
                    timeout_seconds=settings.provider_timeout_seconds,
                ),
                ElevenLabsProvider(
                    settings.elevenlabs,
                    pricing.get("elevenlabs", {}).get("scribe-v2"),
                    timeout_seconds=settings.provider_timeout_seconds,
                ),
                GroqProvider(
                    settings.groq,
                    pricing.get("groq", {}),
                    timeout_seconds=settings.provider_timeout_seconds,
                ),
            ]
        )

    def get_provider(self, provider_id: str) -> TranscriptionProvider:
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            raise OpenTranscribeError(
                ErrorCode.UNSUPPORTED_PROVIDER, f"Unsupported provider: {provider_id}."
            ) from exc

    def get_model(self, provider_id: str, model: str) -> ModelDescriptor:
        try:
            return self.models[f"{provider_id}/{model}"]
        except KeyError as exc:
            raise OpenTranscribeError(
                ErrorCode.UNSUPPORTED_MODEL,
                f"Unsupported model: {provider_id}/{model}.",
                provider=provider_id,
                model=model,
            ) from exc

    def list_models(self) -> list[ModelDescriptor]:
        return list(self.models.values())


def load_pricing(path: Path) -> dict[str, dict[str, PricingDescriptor | None]]:
    if not path.exists():
        return {}
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    providers = raw.get("providers", {})
    return {
        str(provider): {
            str(model): PricingDescriptor.model_validate(descriptor)
            for model, descriptor in models.items()
        }
        for provider, models in providers.items()
    }
