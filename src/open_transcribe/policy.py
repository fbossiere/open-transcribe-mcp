"""Managed authorization policy, enforced by the engine.

A credential in the keyring does not authorize a provider, a checkbox in a window does not
authorize temporary audio processing, and a client prompt does not authorize a second provider.
This object is the authorization boundary; the router, the service, and the source broker all
consult it, so no single missed call can disclose audio to an unauthorized recipient.
"""

from dataclasses import dataclass

from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError


@dataclass(frozen=True, slots=True)
class TranscriptionPolicy:
    """What this installation is permitted to do, independent of what it is able to do."""

    enabled_providers: frozenset[str] | None = None
    """`None` means the deployment imposes no allow-list: the hosted and CLI contract."""

    allow_cross_provider_fallback: bool = True
    allow_temporary_audio: bool = True

    @classmethod
    def unrestricted(cls) -> "TranscriptionPolicy":
        """The existing CLI, container, and hosted contract, unchanged."""
        return cls()

    @property
    def restricted(self) -> bool:
        return self.enabled_providers is not None

    def permits_provider(self, provider_id: str) -> bool:
        return self.enabled_providers is None or provider_id in self.enabled_providers

    def require_provider(self, provider_id: str, *, model: str | None = None) -> None:
        """Fail before any provider attempt, including one reached through fallback."""
        if self.permits_provider(provider_id):
            return
        raise OpenTranscribeError(
            ErrorCode.PROVIDER_NOT_ENABLED,
            f"{provider_id} is not enabled for this installation.",
            provider=provider_id,
            model=model,
        )

    def require_temporary_audio(self, *, provider: str, model: str) -> None:
        """Fail before the source is downloaded, not after."""
        if self.allow_temporary_audio:
            return
        raise OpenTranscribeError(
            ErrorCode.TEMPORARY_AUDIO_NOT_PERMITTED,
            "This model must receive the audio itself, and temporary audio processing is not "
            "permitted for this installation.",
            provider=provider,
            model=model,
        )
