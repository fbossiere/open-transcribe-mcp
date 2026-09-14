"""CFG-01, CLI-05 and CLI-06: the apply transaction, its recovery record, and its limits."""

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from open_transcribe.desktop.clients.json_store import JsonMcpServersAdapter
from open_transcribe.desktop.credentials import InMemoryCredentialStore
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.journal import ResourceKind, load_journal
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.providers import CheckOutcome
from open_transcribe.desktop.schema import ManagedPrivacy, ManagedSelection
from open_transcribe.desktop.setup import ProviderIntent, SetupIntent, SetupService
from open_transcribe.desktop.store import load_managed_config


@pytest.fixture
def client_config(tmp_path: Path) -> Path:
    path = tmp_path / "client" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    return path


@pytest.fixture
def adapter(client_config: Path) -> JsonMcpServersAdapter:
    return JsonMcpServersAdapter(
        adapter_id="demo", display_name="Demo client", config_path=client_config
    )


@pytest.fixture
def service(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore, engine_stub: Path
) -> SetupService:
    return SetupService(desktop_paths, credentials, engine_stub, application_version="1.1.0")


def groq_intent(
    adapter: JsonMcpServersAdapter | None = None, *, key: str = "first-key", takeover: bool = False
) -> SetupIntent:
    return SetupIntent(
        providers=(
            ProviderIntent(
                provider_id="groq",
                enabled=True,
                secrets={"api_key": SecretStr(key)},
                check_outcome=CheckOutcome.PASSED,
            ),
        ),
        selection=ManagedSelection(provider="groq", model="whisper-large-v3-turbo"),
        adapter=adapter,
        takeover=takeover,
    )


def test_planning_writes_nothing(
    service: SetupService, adapter: JsonMcpServersAdapter, client_config: Path
) -> None:
    before = client_config.read_text(encoding="utf-8")
    plan = service.plan(groq_intent(adapter))
    assert plan.provider_recipients == ("groq",)
    assert plan.new_credentials == ("groq:api_key",)
    assert not service.paths.config_file.exists()
    assert client_config.read_text(encoding="utf-8") == before


def test_a_full_apply_records_each_phase_separately(
    service: SetupService,
    adapter: JsonMcpServersAdapter,
    credentials: InMemoryCredentialStore,
) -> None:
    intent = groq_intent(adapter)
    outcome = service.apply(service.plan(intent), intent)
    assert outcome.config_saved
    assert outcome.engine is not None
    assert outcome.engine.ok
    assert outcome.registered
    assert outcome.readback is not None
    assert outcome.failure is None

    config = load_managed_config(service.paths.config_file)
    assert config.enabled_providers == {"groq"}
    ref = config.providers["groq"].credentials["api_key"]
    assert credentials.get(ref) is not None
    assert credentials.get(ref).get_secret_value() == "first-key"  # type: ignore[union-attr]

    journal = load_journal(service.paths.journal_file, config.installation_id)
    assert [(phase.name, phase.state) for phase in journal.phases] == [
        ("credentials", "intended"),
        ("credentials", "applied"),
        ("config", "intended"),
        ("config", "applied"),
        ("engine", "intended"),
        ("engine", "applied"),
        ("client", "intended"),
        ("client", "applied"),
    ]
    assert journal.incomplete == []
    assert journal.owns(ResourceKind.CLIENT_REGISTRATION, "demo:open-transcribe")


def test_no_secret_reaches_the_configuration_or_the_journal(
    service: SetupService, adapter: JsonMcpServersAdapter, client_config: Path
) -> None:
    intent = groq_intent(adapter, key="super-secret-value")
    service.apply(service.plan(intent), intent)
    for path in (service.paths.config_file, service.paths.journal_file, client_config):
        assert "super-secret-value" not in path.read_text(encoding="utf-8")


def test_a_successful_replacement_retires_the_old_key(
    service: SetupService, credentials: InMemoryCredentialStore
) -> None:
    first = groq_intent()
    service.apply(service.plan(first), first)
    old_ref = (
        load_managed_config(service.paths.config_file).providers["groq"].credentials["api_key"]
    )

    second = groq_intent(key="second-key")
    service.apply(service.plan(second), second)
    new_ref = (
        load_managed_config(service.paths.config_file).providers["groq"].credentials["api_key"]
    )

    assert new_ref.account != old_ref.account
    assert credentials.get(new_ref).get_secret_value() == "second-key"  # type: ignore[union-attr]
    assert credentials.get(old_ref) is None


def test_a_failed_replacement_preserves_the_working_key(
    service: SetupService, credentials: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CFG-01: a failure must never leave the user with no key at all."""
    first = groq_intent()
    service.apply(service.plan(first), first)
    original = load_managed_config(service.paths.config_file)
    old_ref = original.providers["groq"].credentials["api_key"]

    second = groq_intent(key="doomed-key")
    plan = service.plan(second)

    def refuse(*_: object, **__: object) -> None:
        raise DesktopError(DesktopErrorCode.KEYRING_LOCKED, "locked")

    monkeypatch.setattr(credentials, "put", refuse)
    outcome = service.apply(plan, second)

    assert outcome.failure is not None
    assert outcome.failure.code is DesktopErrorCode.KEYRING_LOCKED
    assert not outcome.config_saved
    current = load_managed_config(service.paths.config_file)
    assert current.providers["groq"].credentials["api_key"].account == old_ref.account
    assert credentials.get(old_ref).get_secret_value() == "first-key"  # type: ignore[union-attr]


def test_a_client_refusal_keeps_the_saved_setup(
    service: SetupService, adapter: JsonMcpServersAdapter, client_config: Path
) -> None:
    """CLI-06: the failure is visible and retryable; a working setup is not destroyed."""
    client_config.write_text(
        json.dumps({"mcpServers": {"open-transcribe": {"command": "/usr/bin/other"}}}),
        encoding="utf-8",
    )
    intent = groq_intent(adapter)
    outcome = service.apply(service.plan(intent), intent)

    assert outcome.config_saved
    assert not outcome.registered
    assert outcome.failure is not None
    assert outcome.failure.code is DesktopErrorCode.CLIENT_CONFLICT
    assert outcome.repair_needed == ("client",)
    config = load_managed_config(service.paths.config_file)
    journal = load_journal(service.paths.journal_file, config.installation_id)
    assert [phase.name for phase in journal.incomplete] == ["client"]


def test_a_rerun_after_a_client_failure_reconciles(
    service: SetupService, adapter: JsonMcpServersAdapter, client_config: Path
) -> None:
    """CLI-05: rerunning resumes rather than duplicating."""
    client_config.write_text(
        json.dumps({"mcpServers": {"open-transcribe": {"command": "/usr/bin/other"}}}),
        encoding="utf-8",
    )
    intent = groq_intent(adapter)
    service.apply(service.plan(intent), intent)

    retry = groq_intent(adapter, takeover=True)
    outcome = service.apply(service.plan(retry), retry)
    assert outcome.registered
    document = json.loads(client_config.read_text(encoding="utf-8"))
    assert sorted(document["mcpServers"]) == ["open-transcribe"]
    config = load_managed_config(service.paths.config_file)
    journal = load_journal(service.paths.journal_file, config.installation_id)
    assert journal.incomplete == []


def test_a_broken_engine_blocks_client_registration(
    desktop_paths: DesktopPaths,
    credentials: InMemoryCredentialStore,
    adapter: JsonMcpServersAdapter,
    client_config: Path,
    tmp_path: Path,
) -> None:
    """A client is never pointed at an engine that has not answered."""
    broken = tmp_path / "broken-engine"
    broken.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    broken.chmod(0o755)
    service = SetupService(desktop_paths, credentials, broken)
    intent = groq_intent(adapter)
    outcome = service.apply(service.plan(intent), intent)

    assert outcome.config_saved
    assert outcome.engine is not None
    assert not outcome.engine.ok
    assert not outcome.registered
    assert outcome.repair_needed == ("engine",)
    assert json.loads(client_config.read_text(encoding="utf-8"))["mcpServers"] == {}


def test_disconnect_removes_only_the_owned_registration(
    service: SetupService, adapter: JsonMcpServersAdapter, client_config: Path
) -> None:
    intent = groq_intent(adapter)
    service.apply(service.plan(intent), intent)
    document = json.loads(client_config.read_text(encoding="utf-8"))
    document["mcpServers"]["notes"] = {"command": "/usr/bin/notes"}
    client_config.write_text(json.dumps(document), encoding="utf-8")

    outcome = service.disconnect(adapter)
    assert outcome.restart_required
    remaining = json.loads(client_config.read_text(encoding="utf-8"))["mcpServers"]
    assert sorted(remaining) == ["notes"]

    config = load_managed_config(service.paths.config_file)
    assert config.client is None
    # Settings and credentials survive a disconnection by default.
    assert config.enabled_providers == {"groq"}
    assert config.providers["groq"].credentials["api_key"] is not None


def test_erase_is_separate_and_clears_owned_credentials(
    service: SetupService, adapter: JsonMcpServersAdapter, credentials: InMemoryCredentialStore
) -> None:
    intent = groq_intent(adapter)
    service.apply(service.plan(intent), intent)
    config = load_managed_config(service.paths.config_file)
    ref = config.providers["groq"].credentials["api_key"]

    service.disconnect(adapter)
    outcome = service.erase()

    assert outcome.repair_needed == ()
    assert credentials.get(ref) is None
    assert not service.paths.config_file.exists()
    # The journal survives, because it is the only record of what this installation owned.
    assert service.paths.journal_file.exists()


def test_temporary_audio_stays_off_unless_it_is_asked_for(service: SetupService) -> None:
    plan = service.plan(groq_intent())
    assert plan.config.privacy.temporary_audio_processing is False
    assert plan.config.privacy.cross_provider_fallback is False
    assert plan.needs_cleanup_timer is False

    permissive = SetupIntent(
        providers=groq_intent().providers,
        privacy=ManagedPrivacy(temporary_audio_processing=True),
    )
    assert service.plan(permissive).needs_cleanup_timer is True


class _FakeTimer:
    """A cleanup timer that records what it was asked to do, without touching systemd."""

    def __init__(self, *, installable: bool = True) -> None:
        self.installed = False
        self.installable = installable
        self.calls: list[str] = []

    def install(self) -> None:
        self.calls.append("install")
        if not self.installable:
            raise DesktopError(DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE, "no timer here")
        self.installed = True

    def remove(self) -> bool:
        self.calls.append("remove")
        self.installed = False
        return True


def relay_intent(adapter: JsonMcpServersAdapter | None = None, *, allow: bool) -> SetupIntent:
    base = groq_intent(adapter)
    return SetupIntent(
        providers=base.providers,
        selection=base.selection,
        privacy=ManagedPrivacy(temporary_audio_processing=allow),
        adapter=adapter,
    )


def test_the_cleanup_timer_follows_the_temporary_processing_permission(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore, engine_stub: Path
) -> None:
    timer = _FakeTimer()
    service = SetupService(desktop_paths, credentials, engine_stub, cleanup_timer=timer)

    off = relay_intent(allow=False)
    service.apply(service.plan(off), off)
    assert timer.calls == []

    on = relay_intent(allow=True)
    service.apply(service.plan(on), on)
    assert timer.installed
    journal = load_journal(desktop_paths.journal_file, "0" * 32)
    assert journal.owns(ResourceKind.CLEANUP_TIMER, "open-transcribe-cleanup.timer")

    # Withdrawing the permission removes the mechanism it justified.
    again_off = relay_intent(allow=False)
    service.apply(service.plan(again_off), again_off)
    assert not timer.installed
    assert timer.calls == ["install", "remove"]


def test_a_session_that_cannot_expire_files_refuses_the_permission(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore, engine_stub: Path
) -> None:
    """If the expiry mechanism is unavailable, relay stays unavailable rather than unbounded."""
    timer = _FakeTimer(installable=False)
    service = SetupService(desktop_paths, credentials, engine_stub, cleanup_timer=timer)
    intent = relay_intent(allow=True)
    outcome = service.apply(service.plan(intent), intent)

    assert outcome.failure is not None
    assert outcome.failure.code is DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE
    assert outcome.repair_needed == ("cleanup_timer",)
    assert not outcome.registered
    assert not timer.installed


def test_erase_clears_temporary_data_before_removing_its_sweeper(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore, engine_stub: Path
) -> None:
    from open_transcribe.desktop.tempaudio import TemporaryAudioArea

    timer = _FakeTimer()
    service = SetupService(desktop_paths, credentials, engine_stub, cleanup_timer=timer)
    intent = relay_intent(allow=True)
    service.apply(service.plan(intent), intent)

    area = TemporaryAudioArea.for_runtime_dir(desktop_paths.runtime_dir)
    leftover = Path(area.create_file())
    assert leftover.exists()

    outcome = service.erase(temporary_audio=area)
    assert outcome.repair_needed == ()
    assert not leftover.exists()
    assert not timer.installed
    # The purge is recorded before the removal, so nothing is stranded without a sweeper.
    assert timer.calls == ["install", "remove"]
