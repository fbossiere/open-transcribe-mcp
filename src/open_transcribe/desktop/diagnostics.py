"""The shared, typed diagnostic service.

The window and the `doctor` command use the same checks, so what a user reads and what a
maintainer receives cannot drift. None of this is reachable as an MCP tool.

Export rules: a check may hold local detail the user can expand, but `to_export()` returns only
an allowlisted projection. No credential, source URL, endpoint or resource name, username, home
path, client configuration content, transcript, phrase hint, or raw subprocess or provider
response ever leaves this module.
"""

import os
import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from open_transcribe.desktop.credentials import (
    CredentialStore,
    SecretServiceCredentialStore,
)
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.installation import current_installation
from open_transcribe.desktop.journal import load_journal
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.providers import descriptor_for
from open_transcribe.desktop.schema import ManagedConfig
from open_transcribe.desktop.store import load_managed_config
from open_transcribe.desktop.tempaudio import TemporaryAudioArea


class Severity(StrEnum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


_ORDER = {Severity.OK: 0, Severity.INFO: 1, Severity.WARNING: 2, Severity.ERROR: 3}


@dataclass(frozen=True, slots=True)
class Check:
    check_id: str
    title: str
    severity: Severity
    code: str
    recovery: str | None = None
    detail: str | None = None
    """Shown locally behind Details. Never exported."""

    def to_export(self) -> dict[str, Any]:
        return {
            "id": self.check_id,
            "severity": self.severity.value,
            "code": self.code,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    checks: tuple[Check, ...] = field(default_factory=tuple)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    application_version: str = ""
    os_release: str = ""
    session_type: str = "unknown"

    @property
    def worst(self) -> Severity:
        return max(
            (check.severity for check in self.checks),
            key=_ORDER.__getitem__,
            default=Severity.OK,
        )

    def to_export(self) -> dict[str, Any]:
        """The allowlisted support export. This is what Copy diagnostic previews and copies."""
        return {
            "schema": "open-transcribe-diagnostic/1",
            "generated_at": self.generated_at.isoformat(),
            "application_version": self.application_version,
            "os_release": self.os_release,
            "session_type": self.session_type,
            "worst_severity": self.worst.value,
            "checks": [check.to_export() for check in self.checks],
        }


def run_diagnostics(
    config_path: Path | None = None,
    *,
    paths: DesktopPaths | None = None,
    credentials: CredentialStore | None = None,
    check_engine: bool = False,
) -> DiagnosticReport:
    resolved = paths or DesktopPaths.resolve()
    target = config_path or resolved.config_file
    installation = current_installation()
    checks: list[Check] = [_privilege_check(), _session_check()]

    config, config_check = _config_check(target)
    checks.append(config_check)
    checks.append(_keyring_check(credentials))
    checks.append(_engine_installed_check(installation.engine))
    if config is not None:
        checks.extend(_provider_checks(config, credentials))
        checks.append(_temporary_audio_check(config, resolved))
        checks.append(_client_check(config))
        checks.append(_journal_check(resolved, config))
        if check_engine:
            checks.append(_engine_handshake_check(installation.engine, target))
    return DiagnosticReport(
        checks=tuple(checks),
        application_version=installation.version,
        os_release=_os_release(),
        session_type=os.environ.get("XDG_SESSION_TYPE", "unknown"),
    )


def _privilege_check() -> Check:
    if os.geteuid() == 0:
        return Check(
            "platform.privilege",
            "Running as root",
            Severity.ERROR,
            "privilege.root",
            "Sign in as your normal user and open OpenTranscribe Setup from the menu.",
        )
    return Check("platform.privilege", "Running as your own user", Severity.OK, "privilege.user")


def _session_check() -> Check:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    if session in {"wayland", "x11"}:
        return Check("platform.session", "Graphical session", Severity.OK, f"session.{session}")
    return Check(
        "platform.session",
        "No graphical session detected",
        Severity.WARNING,
        "session.headless",
        "Setup needs a normal desktop session with a keyring. The engine itself does not.",
    )


def _config_check(path: Path) -> tuple[ManagedConfig | None, Check]:
    try:
        config = load_managed_config(path)
    except DesktopError as exc:
        severity = Severity.INFO if exc.code is DesktopErrorCode.CONFIG_MISSING else Severity.ERROR
        title = (
            "No saved setup yet"
            if exc.code is DesktopErrorCode.CONFIG_MISSING
            else "Saved setup cannot be used"
        )
        return None, Check("config.load", title, severity, exc.code.value, exc.recovery)
    return config, Check("config.load", "Saved setup is readable", Severity.OK, "config.valid")


def _keyring_check(credentials: CredentialStore | None) -> Check:
    if credentials is not None:
        return Check("keyring.backend", "Keyring provided", Severity.OK, "keyring.injected")
    try:
        SecretServiceCredentialStore()
    except DesktopError as exc:
        return Check(
            "keyring.backend", "Keyring unavailable", Severity.ERROR, exc.code.value, exc.recovery
        )
    return Check("keyring.backend", "Session keyring available", Severity.OK, "keyring.ready")


def _engine_installed_check(engine: Path) -> Check:
    if engine.is_file() and os.access(engine, os.X_OK):
        return Check("engine.installed", "Packaged engine present", Severity.OK, "engine.present")
    return Check(
        "engine.installed",
        "Packaged engine missing",
        Severity.ERROR,
        DesktopErrorCode.ENGINE_MISSING.value,
        "Reinstall the OpenTranscribe Setup package.",
    )


def _provider_checks(config: ManagedConfig, credentials: CredentialStore | None) -> list[Check]:
    enabled = sorted(config.enabled_providers)
    if not enabled:
        return [
            Check(
                "providers.enabled",
                "No transcription provider is enabled",
                Severity.ERROR,
                "providers.none",
                "Open Manage providers and enable one.",
            )
        ]
    checks = [
        Check(
            "providers.enabled",
            f"{len(enabled)} provider(s) enabled",
            Severity.OK,
            "providers.enabled",
        )
    ]
    store = credentials
    if store is None:
        try:
            store = SecretServiceCredentialStore()
        except DesktopError:
            return checks
    missing: list[str] = []
    for provider_id in enabled:
        managed = config.providers[provider_id]
        for role in descriptor_for(provider_id).credential_roles:
            ref = managed.credentials.get(role)
            if ref is None or store.get(ref) is None:
                missing.append(f"{provider_id}:{role}")
    if missing:
        checks.append(
            Check(
                "providers.credentials",
                "A saved key is missing from the keyring",
                Severity.ERROR,
                "credential.missing",
                "Open Manage providers and enter the key again.",
                detail=", ".join(missing),
            )
        )
    else:
        checks.append(
            Check(
                "providers.credentials",
                "Saved keys resolve in the keyring",
                Severity.OK,
                "credential.present",
            )
        )
    unchecked = [
        provider_id
        for provider_id in enabled
        if config.providers[provider_id].check_outcome != "passed"
    ]
    if unchecked:
        checks.append(
            Check(
                "providers.verified",
                "Key saved — transcription not tested",
                Severity.INFO,
                "check.not_tested",
                "Transcribe the public sample to test it, or leave it untested.",
            )
        )
    return checks


def _temporary_audio_check(config: ManagedConfig, paths: DesktopPaths) -> Check:
    if not config.privacy.temporary_audio_processing:
        return Check(
            "privacy.temporary_audio",
            "Temporary audio processing is off",
            Severity.OK,
            "temp_audio.off",
        )
    try:
        area = TemporaryAudioArea.for_runtime_dir(
            paths.runtime_dir, ttl_seconds=config.privacy.temporary_audio_ttl_seconds
        )
        area.prepare()
    except DesktopError as exc:
        return Check(
            "privacy.temporary_audio",
            "Temporary audio processing cannot expire reliably",
            Severity.ERROR,
            exc.code.value,
            exc.recovery,
        )
    report = area.sweep()
    return Check(
        "privacy.temporary_audio",
        f"Temporary audio area ready ({report.retained} in use)",
        Severity.OK if report.complete else Severity.WARNING,
        "temp_audio.ready" if report.complete else "temp_audio.cleanup_failed",
        None if report.complete else "Run Repair connection to retry the cleanup.",
    )


def _client_check(config: ManagedConfig) -> Check:
    if config.client is None:
        return Check(
            "client.registration",
            "No assistant is connected",
            Severity.INFO,
            "client.none",
            "Open Setup and choose Connect your assistant.",
        )
    if config.client.activation == "observed":
        return Check(
            "client.registration", "Active in your assistant", Severity.OK, "client.active"
        )
    if config.client.activation == "user_confirmed":
        return Check(
            "client.registration",
            "Connection saved — you confirmed it works",
            Severity.OK,
            "client.user_confirmed",
        )
    return Check(
        "client.registration",
        "Connection saved — check it in your assistant",
        Severity.INFO,
        "client.unverified",
        "Open your assistant and ask it to list OpenTranscribe models.",
    )


def _journal_check(paths: DesktopPaths, config: ManagedConfig) -> Check:
    try:
        journal = load_journal(paths.journal_file, config.installation_id)
    except DesktopError as exc:
        return Check(
            "journal.state",
            "Recovery journal unreadable",
            Severity.WARNING,
            exc.code.value,
            exc.recovery,
        )
    incomplete = journal.incomplete
    if not incomplete and not journal.pending_cleanup:
        return Check("journal.state", "No unfinished changes", Severity.OK, "journal.clean")
    return Check(
        "journal.state",
        "An earlier change did not finish",
        Severity.WARNING,
        "journal.incomplete",
        "Run Repair connection to finish it.",
        detail=", ".join(sorted({phase.name for phase in incomplete})),
    )


def _engine_handshake_check(engine: Path, config_path: Path) -> Check:
    from open_transcribe.desktop.engine_probe import probe_engine

    try:
        result = probe_engine(engine, config_path)
    except DesktopError as exc:
        return Check(
            "engine.handshake", "Engine unavailable", Severity.ERROR, exc.code.value, exc.recovery
        )
    if result.ok:
        return Check(
            "engine.handshake",
            "Engine answers with the expected tools",
            Severity.OK,
            "engine.ready",
        )
    return Check(
        "engine.handshake",
        "Engine did not answer as expected",
        Severity.ERROR,
        result.reason,
        "Run Repair connection, or reinstall the package.",
    )


def _os_release() -> str:
    """A coarse platform string. Never the hostname, the user, or a path."""
    try:
        fields = dict(
            line.split("=", 1)
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    except OSError:
        return platform.system()
    return fields.get("PRETTY_NAME", platform.system()).strip('"')
