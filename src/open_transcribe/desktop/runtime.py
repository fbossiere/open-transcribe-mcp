"""Turning a managed configuration into an engine runtime.

This is the only bridge between the desktop profile and the transcription engine. It builds
settings from explicit values, resolves credential references inside the engine process, and
derives the authorization policy the engine enforces.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from open_transcribe.desktop.credentials import (
    CredentialStore,
    SecretServiceCredentialStore,
)
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.providers import descriptor_for, validate_credential_endpoint
from open_transcribe.desktop.schema import ManagedConfig, ManagedProvider
from open_transcribe.desktop.store import load_managed_config
from open_transcribe.desktop.tempaudio import TemporaryAudioArea
from open_transcribe.policy import TranscriptionPolicy
from open_transcribe.settings import ExplicitSettings, Settings

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class ManagedRuntime:
    """Everything the engine needs under managed mode, and nothing the user did not approve."""

    config: ManagedConfig
    settings: Settings
    policy: TranscriptionPolicy
    temporary_audio: TemporaryAudioArea | None
    unresolved_credentials: tuple[str, ...] = ()
    credential_error: str | None = None
    """A normalized keyring failure code, when one prevented a key from being resolved."""


def refuse_root() -> None:
    """Desktop setup and the managed engine are per-user operations. Root is a packaging role."""
    if os.geteuid() == 0:
        raise DesktopError(
            DesktopErrorCode.PRIVILEGE_REFUSED,
            "OpenTranscribe Setup runs as your own user account, not as root.",
            recovery="Sign in as your normal user and open OpenTranscribe Setup from the menu.",
        )


def build_managed_runtime(
    config_path: Path,
    *,
    credentials: CredentialStore | None = None,
    paths: DesktopPaths | None = None,
) -> ManagedRuntime:
    config = load_managed_config(config_path)
    return runtime_from_config(config, credentials=credentials, paths=paths)


def runtime_from_config(
    config: ManagedConfig,
    *,
    credentials: CredentialStore | None = None,
    paths: DesktopPaths | None = None,
) -> ManagedRuntime:
    resolved = paths or DesktopPaths.resolve()
    enabled = config.enabled_providers
    store, credential_error = (
        (credentials, None) if credentials is not None else _lazy_store(enabled)
    )
    provider_values, unresolved = _provider_settings(config, store)

    temporary_audio = None
    if config.privacy.temporary_audio_processing:
        # If the session cannot provide the expiry mechanism, the permission stays unavailable
        # rather than degrading into unbounded storage.
        temporary_audio = TemporaryAudioArea.for_runtime_dir(
            resolved.runtime_dir, ttl_seconds=config.privacy.temporary_audio_ttl_seconds
        )
        temporary_audio.prepare()

    settings = ExplicitSettings(
        environment="prod",
        transport="stdio",
        # STDIO opens no socket; the loopback value documents that nothing here is bindable.
        host="127.0.0.1",
        port=1,
        default_provider=config.selection.provider or "microsoft",
        default_model=config.selection.model or "MAI-Transcribe-2",
        request_timeout_seconds=config.limits.request_timeout_seconds,
        provider_timeout_seconds=config.limits.provider_timeout_seconds,
        max_audio_size_mb=config.limits.max_audio_size_mb,
        max_audio_duration_seconds=config.limits.max_audio_duration_seconds,
        max_request_cost_usd=config.limits.estimated_cost_threshold_usd,
        security={"auth_mode": "none"},
        # Desktop V1 keeps transcript storage disabled; the schema admits no other value.
        result_store={"backend": config.privacy.transcript_store},
        **provider_values,
    )
    policy = TranscriptionPolicy(
        enabled_providers=enabled,
        allow_cross_provider_fallback=config.privacy.cross_provider_fallback,
        allow_temporary_audio=config.privacy.temporary_audio_processing,
    )
    return ManagedRuntime(
        config=config,
        settings=settings,
        policy=policy,
        temporary_audio=temporary_audio,
        unresolved_credentials=unresolved,
        credential_error=credential_error,
    )


def _lazy_store(enabled: frozenset[str]) -> tuple[CredentialStore | None, str | None]:
    """Reach for the keyring only when an enabled provider needs a secret.

    An unavailable or locked keyring does not stop the engine. It leaves the affected providers
    unconfigured, which the MCP tools report plainly, and which OpenTranscribe Setup diagnoses
    with a specific recovery path. Engine readiness and provider readiness are separate claims,
    and neither is ever inferred from the other.
    """
    if not enabled:
        return None, None
    try:
        return SecretServiceCredentialStore(), None
    except DesktopError as exc:
        logger.warning("managed_keyring_unavailable", code=exc.code.value)
        return None, exc.code.value


def _provider_settings(
    config: ManagedConfig, store: CredentialStore | None
) -> tuple[dict[str, Any], tuple[str, ...]]:
    values: dict[str, Any] = {}
    unresolved: list[str] = []
    for provider_id, managed in config.providers.items():
        if not managed.enabled:
            # A stored key is not an authorization. An unenabled provider contributes nothing to
            # the engine's settings, so it cannot become configured or routable by accident.
            continue
        descriptor = descriptor_for(provider_id)
        section: dict[str, Any] = {}
        if managed.endpoint is not None:
            section["endpoint"] = validate_credential_endpoint(str(managed.endpoint))
        if managed.api_version:
            section["api_version"] = managed.api_version
        if descriptor.zero_retention_control:
            section["zero_retention"] = True
        missing = _resolve_roles(descriptor.credential_roles, managed, store, section)
        unresolved.extend(f"{provider_id}:{role}" for role in missing)
        if missing:
            logger.warning(
                "managed_credential_unresolved", provider=provider_id, roles=sorted(missing)
            )
        values[descriptor.settings_key] = section
    return values, tuple(unresolved)


def _resolve_roles(
    roles: tuple[str, ...],
    managed: ManagedProvider,
    store: CredentialStore | None,
    section: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    for role in roles:
        ref = managed.credentials.get(role)
        secret = None
        if ref is not None and store is not None:
            try:
                secret = store.get(ref)
            except DesktopError as exc:
                logger.warning("managed_credential_unreadable", role=role, code=exc.code.value)
        if secret is None:
            missing.append(role)
            continue
        section[role] = secret
    return missing
