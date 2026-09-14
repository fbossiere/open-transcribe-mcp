"""The setup transaction: plan, apply, verify, repair, disconnect.

The configuration file, the keyring, and a client's own store have no shared transaction
manager, so this module does not pretend otherwise. Every phase records its intent before it
acts and its observed result after, and a failure compensates only what this transaction safely
owns. An interrupted run is resumable; it is never reported as a clean success or a clean
rollback it cannot substantiate.
"""

import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from open_transcribe.desktop.cleanup_timer import TIMER_NAME, CleanupTimer
from open_transcribe.desktop.clients.base import (
    ClientAdapter,
    ExistingEntry,
    RegistrationPlan,
    ServerRegistration,
)
from open_transcribe.desktop.credentials import CredentialStore, new_credential_ref
from open_transcribe.desktop.engine_probe import EngineProbeResult, probe_engine
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.journal import (
    InstallJournal,
    OwnedResource,
    ResourceKind,
    load_journal,
    save_journal,
)
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.providers import CheckOutcome, descriptor_for
from open_transcribe.desktop.schema import (
    SCHEMA_VERSION,
    CredentialRef,
    ManagedClient,
    ManagedConfig,
    ManagedLimits,
    ManagedPrivacy,
    ManagedProvider,
    ManagedSelection,
)
from open_transcribe.desktop.store import (
    installation_lock,
    load_managed_config,
    save_managed_config,
)
from open_transcribe.desktop.tempaudio import TemporaryAudioArea


def new_installation_id() -> str:
    return secrets.token_hex(16)


@dataclass(frozen=True, slots=True)
class ProviderIntent:
    """One provider as the user left it in the form. Secrets live here only until commit."""

    provider_id: str
    enabled: bool = True
    secrets: dict[str, SecretStr] = field(default_factory=dict)
    endpoint: str | None = None
    api_version: str | None = None
    check_outcome: CheckOutcome = CheckOutcome.NOT_TESTED


@dataclass(frozen=True, slots=True)
class SetupIntent:
    providers: tuple[ProviderIntent, ...] = ()
    selection: ManagedSelection = field(default_factory=ManagedSelection)
    privacy: ManagedPrivacy = field(default_factory=ManagedPrivacy)
    limits: ManagedLimits = field(default_factory=ManagedLimits)
    adapter: ClientAdapter | None = None
    server_name: str = "open-transcribe"
    takeover: bool = False
    locale: str = "system"


@dataclass(frozen=True, slots=True)
class SetupPlan:
    """Exactly what "Enable connection" would authorize, and nothing implied beyond it."""

    config: ManagedConfig
    previous: ManagedConfig | None
    registration: ServerRegistration | None
    registration_plan: RegistrationPlan | None
    new_credentials: tuple[str, ...] = ()
    retired_credentials: tuple[CredentialRef, ...] = ()
    needs_cleanup_timer: bool = False

    @property
    def provider_recipients(self) -> tuple[str, ...]:
        return tuple(sorted(self.config.enabled_providers))


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    """What was observed, phase by phase. Absent evidence is reported as absent."""

    config_saved: bool = False
    credentials_written: tuple[str, ...] = ()
    engine: EngineProbeResult | None = None
    registered: bool = False
    readback: ExistingEntry | None = None
    restart_required: bool = False
    failure: DesktopError | None = None
    repair_needed: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return (
            self.config_saved
            and self.engine is not None
            and self.engine.ok
            and self.failure is None
        )


class SetupService:
    """Drives the managed installation. The GUI and `doctor` share it; MCP never reaches it."""

    def __init__(
        self,
        paths: DesktopPaths,
        credentials: CredentialStore,
        engine: Path,
        *,
        application_version: str | None = None,
        cleanup_timer: CleanupTimer | None = None,
    ) -> None:
        self.paths = paths
        self.credentials = credentials
        self.engine = engine
        self.application_version = application_version
        self.cleanup_timer = cleanup_timer

    # -- reading -------------------------------------------------------------------------

    def current_config(self) -> ManagedConfig | None:
        try:
            return load_managed_config(self.paths.config_file)
        except DesktopError as exc:
            if exc.code is DesktopErrorCode.CONFIG_MISSING:
                return None
            raise

    def journal(self, installation_id: str) -> InstallJournal:
        return load_journal(self.paths.journal_file, installation_id)

    def owned_fingerprints(self, journal: InstallJournal) -> frozenset[str]:
        return frozenset(
            resource.fingerprint
            for resource in journal.resources(ResourceKind.CLIENT_REGISTRATION)
            if resource.fingerprint
        )

    # -- planning ------------------------------------------------------------------------

    def plan(self, intent: SetupIntent) -> SetupPlan:
        """Read state and describe the change. Planning writes nothing, anywhere."""
        previous = self.current_config()
        installation_id = previous.installation_id if previous else new_installation_id()
        providers: dict[str, ManagedProvider] = {}
        new_credentials: list[str] = []
        retired: list[CredentialRef] = []
        for item in intent.providers:
            descriptor = descriptor_for(item.provider_id)
            existing = (previous.providers.get(item.provider_id) if previous else None) or (
                ManagedProvider()
            )
            refs = dict(existing.credentials)
            for role in descriptor.credential_roles:
                if role not in item.secrets:
                    continue
                # A replacement is written to a brand-new item and the reference is moved at
                # commit. A failed replacement therefore leaves the working key untouched.
                if (stale := refs.get(role)) is not None:
                    retired.append(stale)
                refs[role] = new_credential_ref(installation_id, item.provider_id, role)
                new_credentials.append(f"{item.provider_id}:{role}")
            providers[item.provider_id] = ManagedProvider(
                enabled=item.enabled,
                credentials=refs,
                endpoint=item.endpoint or existing.endpoint,
                api_version=item.api_version or existing.api_version,
                checked_at=datetime.now(UTC)
                if item.check_outcome != CheckOutcome.NOT_TESTED
                else existing.checked_at,
                check_outcome=item.check_outcome.value,
            )

        registration = self._registration(intent)
        registration_plan = None
        if intent.adapter is not None and registration is not None:
            journal = self.journal(installation_id)
            registration_plan = intent.adapter.plan(
                registration,
                owned=self.owned_fingerprints(journal),
                takeover=intent.takeover,
            )
        config = ManagedConfig(
            schema_version=SCHEMA_VERSION,
            installation_id=installation_id,
            locale=intent.locale,
            selection=intent.selection,
            providers=providers,
            privacy=intent.privacy,
            limits=intent.limits,
            client=(
                ManagedClient(
                    adapter_id=intent.adapter.adapter_id,
                    display_name=intent.adapter.display_name,
                    server_name=intent.server_name,
                )
                if intent.adapter is not None
                else None
            ),
        )
        return SetupPlan(
            config=config,
            previous=previous,
            registration=registration,
            registration_plan=registration_plan,
            new_credentials=tuple(new_credentials),
            retired_credentials=tuple(retired),
            needs_cleanup_timer=intent.privacy.temporary_audio_processing,
        )

    def _registration(self, intent: SetupIntent) -> ServerRegistration | None:
        if intent.adapter is None:
            return None
        return ServerRegistration(
            name=intent.server_name,
            command=self.engine,
            config_path=self.paths.config_file,
        )

    # -- applying ------------------------------------------------------------------------

    def apply(self, plan: SetupPlan, intent: SetupIntent) -> ApplyOutcome:
        """Apply the reviewed plan under the installation lock."""
        with installation_lock(self.paths):
            return self._apply_locked(plan, intent)

    def _apply_locked(self, plan: SetupPlan, intent: SetupIntent) -> ApplyOutcome:
        journal = self.journal(plan.config.installation_id)
        journal.application_version = self.application_version
        outcome = ApplyOutcome()

        written: list[tuple[str, CredentialRef]] = []
        try:
            journal.record("credentials", "intended")
            written = self._write_credentials(plan, intent)
            for label, ref in written:
                journal.own(
                    OwnedResource(kind=ResourceKind.CREDENTIAL, identifier=f"{ref.account}|{label}")
                )
            journal.record("credentials", "applied")
            save_journal(self.paths.journal_file, journal)
        except DesktopError as exc:
            journal.record("credentials", "failed", exc.code.value)
            self._compensate_credentials(written, journal)
            save_journal(self.paths.journal_file, journal)
            return replace(outcome, failure=exc)
        outcome = replace(outcome, credentials_written=tuple(label for label, _ in written))

        try:
            journal.record("config", "intended")
            save_managed_config(self.paths.config_file, plan.config)
            journal.own(
                OwnedResource(kind=ResourceKind.CONFIG, identifier=str(self.paths.config_file))
            )
            journal.record("config", "applied")
            save_journal(self.paths.journal_file, journal)
        except (DesktopError, OSError) as exc:
            journal.record("config", "failed")
            self._compensate_credentials(written, journal)
            save_journal(self.paths.journal_file, journal)
            return replace(outcome, failure=_as_desktop_error(exc))
        outcome = replace(outcome, config_saved=True)
        self._retire(plan.retired_credentials, journal)
        failure = self._reconcile_cleanup_timer(plan, journal)
        if failure is not None:
            return replace(outcome, failure=failure, repair_needed=("cleanup_timer",))

        # The engine is verified under the committed configuration before a client is ever told
        # to launch it, so a client is never pointed at a server that cannot start.
        journal.record("engine", "intended")
        engine = probe_engine(self.engine, self.paths.config_file)
        journal.record("engine", "applied" if engine.ok else "failed", engine.reason)
        save_journal(self.paths.journal_file, journal)
        outcome = replace(outcome, engine=engine)
        if not engine.ok:
            return replace(
                outcome,
                failure=DesktopError(
                    DesktopErrorCode.ENGINE_HANDSHAKE_FAILED,
                    "The packaged engine did not answer with the expected tools.",
                    recovery="Run Repair connection, or reinstall the package.",
                ),
                repair_needed=("engine",),
            )

        if intent.adapter is None or plan.registration_plan is None or plan.registration is None:
            return outcome
        return self._register(plan, intent, journal, outcome)

    def _register(
        self,
        plan: SetupPlan,
        intent: SetupIntent,
        journal: InstallJournal,
        outcome: ApplyOutcome,
    ) -> ApplyOutcome:
        adapter = intent.adapter
        assert adapter is not None  # noqa: S101 - guarded by the caller
        registration = plan.registration
        assert registration is not None  # noqa: S101 - guarded by the caller
        journal.record("client", "intended")
        try:
            adapter.apply(plan.registration_plan)  # type: ignore[arg-type]
        except DesktopError as exc:
            journal.record("client", "failed", exc.code.value)
            save_journal(self.paths.journal_file, journal)
            # The configuration and credentials stay: they are valid, and removing them would
            # destroy a working setup because one client refused a registration.
            return replace(outcome, failure=exc, repair_needed=("client",))
        entry = adapter.readback(registration.name)
        journal.own(
            OwnedResource(
                kind=ResourceKind.CLIENT_REGISTRATION,
                identifier=f"{adapter.adapter_id}:{registration.name}",
                fingerprint=registration.fingerprint(),
            )
        )
        journal.record("client", "applied", None if entry else "client.readback_unavailable")
        save_journal(self.paths.journal_file, journal)
        return replace(
            outcome,
            registered=True,
            readback=entry,
            restart_required=getattr(adapter, "restart_required", True),
        )

    def _reconcile_cleanup_timer(
        self, plan: SetupPlan, journal: InstallJournal
    ) -> DesktopError | None:
        """Install the sweeper only as part of the approved opt-in, and remove it when it lapses.

        The timer is a consequence of the temporary-processing permission, never a separate
        background service and never something a maintainer script turns on.
        """
        if self.cleanup_timer is None:
            return None
        owned = journal.owns(ResourceKind.CLEANUP_TIMER, TIMER_NAME)
        if plan.needs_cleanup_timer:
            if owned and self.cleanup_timer.installed:
                return None
            journal.record("cleanup_timer", "intended")
            try:
                self.cleanup_timer.install()
            except DesktopError as exc:
                journal.record("cleanup_timer", "failed", exc.code.value)
                save_journal(self.paths.journal_file, journal)
                return exc
            journal.own(OwnedResource(kind=ResourceKind.CLEANUP_TIMER, identifier=TIMER_NAME))
            journal.record("cleanup_timer", "applied")
        elif owned:
            journal.record("cleanup_timer", "intended", "remove")
            if self.cleanup_timer.remove():
                journal.disown(ResourceKind.CLEANUP_TIMER, TIMER_NAME)
                journal.record("cleanup_timer", "applied", "removed")
            else:
                journal.record("cleanup_timer", "failed", "remove")
        else:
            return None
        save_journal(self.paths.journal_file, journal)
        return None

    def _write_credentials(
        self, plan: SetupPlan, intent: SetupIntent
    ) -> list[tuple[str, CredentialRef]]:
        written: list[tuple[str, CredentialRef]] = []
        for item in intent.providers:
            managed = plan.config.providers[item.provider_id]
            for role, secret in item.secrets.items():
                ref = managed.credentials.get(role)
                if ref is None:
                    continue
                self.credentials.put(ref, secret)
                written.append((f"{item.provider_id}:{role}", ref))
        return written

    def _compensate_credentials(
        self, written: list[tuple[str, CredentialRef]], journal: InstallJournal
    ) -> None:
        """Remove only the items this transaction created, and never a reused one."""
        for label, ref in written:
            try:
                self.credentials.delete(ref)
            except DesktopError:
                journal.pending_cleanup.append(
                    OwnedResource(kind=ResourceKind.CREDENTIAL, identifier=ref.account)
                )
            else:
                journal.disown(ResourceKind.CREDENTIAL, f"{ref.account}|{label}")

    def _retire(self, refs: tuple[CredentialRef, ...], journal: InstallJournal) -> None:
        """Delete a replaced key only after the new configuration is committed and readable."""
        for ref in refs:
            try:
                self.credentials.delete(ref)
            except DesktopError:
                journal.pending_cleanup.append(
                    OwnedResource(kind=ResourceKind.CREDENTIAL, identifier=ref.account)
                )
        if refs:
            save_journal(self.paths.journal_file, journal)

    # -- lifecycle -----------------------------------------------------------------------

    def disconnect(self, adapter: ClientAdapter | None = None) -> ApplyOutcome:
        """Remove only owned client registrations. Settings and credentials are preserved."""
        config = self.current_config()
        if config is None:
            return ApplyOutcome()
        with installation_lock(self.paths):
            journal = self.journal(config.installation_id)
            journal.record("disconnect", "intended")
            removed = True
            if config.client is not None and adapter is not None:
                identifier = f"{adapter.adapter_id}:{config.client.server_name}"
                if journal.owns(ResourceKind.CLIENT_REGISTRATION, identifier):
                    try:
                        removed = adapter.remove(config.client.server_name)
                    except DesktopError as exc:
                        journal.record("disconnect", "failed", exc.code.value)
                        save_journal(self.paths.journal_file, journal)
                        return ApplyOutcome(failure=exc, repair_needed=("client",))
                    if removed:
                        journal.disown(ResourceKind.CLIENT_REGISTRATION, identifier)
            updated = config.model_copy(update={"client": None})
            save_managed_config(self.paths.config_file, updated)
            journal.record("disconnect", "applied" if removed else "failed")
            save_journal(self.paths.journal_file, journal)
            return ApplyOutcome(config_saved=True, registered=False, restart_required=True)

    def erase(self, *, temporary_audio: TemporaryAudioArea | None = None) -> ApplyOutcome:
        """Erase the saved setup. Separate from disconnection, and never implied by it."""
        config = self.current_config()
        if config is None:
            return ApplyOutcome()
        with installation_lock(self.paths):
            journal = self.journal(config.installation_id)
            journal.record("erase", "intended")
            pending: list[str] = []
            # Approved temporary data is cleared *before* the mechanism that would have cleaned
            # it is removed, so nothing is stranded without a sweeper.
            if temporary_audio is not None:
                report = temporary_audio.purge()
                if not report.complete:
                    pending.append("temporary_audio")
            if self.cleanup_timer is not None and journal.owns(
                ResourceKind.CLEANUP_TIMER, TIMER_NAME
            ):
                if self.cleanup_timer.remove():
                    journal.disown(ResourceKind.CLEANUP_TIMER, TIMER_NAME)
                else:
                    pending.append("cleanup_timer")
            for provider in config.providers.values():
                for ref in provider.credentials.values():
                    try:
                        self.credentials.delete(ref)
                    except DesktopError:
                        pending.append(f"credential:{ref.account}")
                    else:
                        journal.disown(ResourceKind.CREDENTIAL, ref.account)
            self.paths.config_file.unlink(missing_ok=True)
            journal.disown(ResourceKind.CONFIG, str(self.paths.config_file))
            journal.record("erase", "applied" if not pending else "failed")
            # The journal survives an incomplete erase: it is the only record of what still
            # needs cleaning up, and reporting success while losing it would strand the user.
            save_journal(self.paths.journal_file, journal)
            return ApplyOutcome(config_saved=True, repair_needed=tuple(pending))


def _as_desktop_error(exc: Exception) -> DesktopError:
    if isinstance(exc, DesktopError):
        return exc
    return DesktopError(DesktopErrorCode.CONFIG_INVALID, "The saved setup could not be written.")
