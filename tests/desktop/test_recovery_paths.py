"""The recovery paths §13 requires: each failure has its own specific answer."""

import json
import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from open_transcribe.cli import run_cli
from open_transcribe.desktop.clients.base import ServerRegistration, SupportStatus
from open_transcribe.desktop.clients.json_store import JsonMcpServersAdapter
from open_transcribe.desktop.clients.manual import ManualRegistrationAdapter
from open_transcribe.desktop.clients.registry import build_adapters, load_matrix
from open_transcribe.desktop.credentials import (
    InMemoryCredentialStore,
    SecretServiceCredentialStore,
    new_credential_ref,
)
from open_transcribe.desktop.diagnostics import Severity, run_diagnostics
from open_transcribe.desktop.engine_probe import EXPECTED_TOOLS, probe_engine, require_executable
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.installation import current_installation, engine_executable
from open_transcribe.desktop.journal import (
    InstallJournal,
    OwnedResource,
    ResourceKind,
    load_journal,
    save_journal,
)
from open_transcribe.desktop.paths import DesktopPaths, write_private_file
from open_transcribe.desktop.schema import ManagedConfig
from open_transcribe.desktop.store import save_managed_config

ENGINE = Path("/opt/open-transcribe-assistant/open-transcribe-mcp")
CONFIG = Path("/home/user/.config/open-transcribe-mcp/desktop/config.toml")


# -- the command line ---------------------------------------------------------------------


def test_serve_reports_a_managed_failure_with_its_recovery(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_cli(["serve", "--transport", "stdio", "--config", str(tmp_path / "absent.toml")])
    captured = capsys.readouterr()
    assert code == 1
    assert "CONFIG_MISSING" in captured.err
    assert captured.out == ""


def test_doctor_prints_a_readable_report_with_its_recovery_actions(
    desktop_paths: DesktopPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    save_managed_config(
        desktop_paths.config_file, ManagedConfig(schema_version=1, installation_id="0" * 32)
    )
    run_cli(["doctor", "--config", str(desktop_paths.config_file)])
    out = capsys.readouterr().out
    assert "config.load" in out
    assert "->" in out, "a check with a recovery action prints it"


def test_cleanup_sweeps_the_area_and_reports_what_it_did(
    desktop_paths: DesktopPaths, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from open_transcribe.desktop.tempaudio import TemporaryAudioArea

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(desktop_paths.runtime_dir.parent))
    save_managed_config(
        desktop_paths.config_file, ManagedConfig(schema_version=1, installation_id="0" * 32)
    )
    area = TemporaryAudioArea.for_runtime_dir(desktop_paths.runtime_dir)
    leftover = Path(area.create_file())

    assert run_cli(["cleanup-temporary-audio", "--config", str(desktop_paths.config_file)]) == 0
    assert "retained=1" in capsys.readouterr().err
    assert leftover.exists(), "a live owner's unexpired file is left alone"

    assert (
        run_cli(["cleanup-temporary-audio", "--config", str(desktop_paths.config_file), "--purge"])
        == 0
    )
    assert "removed=1" in capsys.readouterr().err
    assert not leftover.exists()


def test_cleanup_without_a_runtime_directory_is_quiet(
    desktop_paths: DesktopPaths, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    save_managed_config(
        desktop_paths.config_file, ManagedConfig(schema_version=1, installation_id="0" * 32)
    )
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert run_cli(["cleanup-temporary-audio", "--config", str(desktop_paths.config_file)]) == 0
    assert "TEMP_AUDIO_UNAVAILABLE" in capsys.readouterr().err


# -- diagnostics --------------------------------------------------------------------------


def test_a_corrupt_configuration_is_an_error_with_a_recovery(desktop_paths: DesktopPaths) -> None:
    write_private_file(desktop_paths.config_file, b"not = = toml")
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=InMemoryCredentialStore()
    )
    check = next(item for item in report.checks if item.check_id == "config.load")
    assert check.severity is Severity.ERROR
    assert check.recovery
    assert report.worst is Severity.ERROR


def test_an_unreadable_journal_is_a_warning_not_a_dead_end(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    save_managed_config(
        desktop_paths.config_file, ManagedConfig(schema_version=1, installation_id="0" * 32)
    )
    write_private_file(desktop_paths.journal_file, b"{not json")
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "journal.state")
    assert check.severity is Severity.WARNING


def test_an_unfinished_change_is_visible_and_says_how_to_finish(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    save_managed_config(
        desktop_paths.config_file, ManagedConfig(schema_version=1, installation_id="0" * 32)
    )
    journal = InstallJournal(installation_id="0" * 32)
    journal.record("client", "intended")
    save_journal(desktop_paths.journal_file, journal)

    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "journal.state")
    assert check.severity is Severity.WARNING
    assert check.recovery == "Run Repair connection to finish it."
    assert check.detail == "client"
    # Local detail never travels: the export carries only id, severity, and code.
    exported = report.to_export()
    assert all(set(item) == {"id", "severity", "code"} for item in exported["checks"])
    assert "detail" not in json.dumps(exported)


def test_temporary_audio_readiness_is_checked_when_it_is_permitted(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    save_managed_config(
        desktop_paths.config_file,
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            privacy={"temporary_audio_processing": True},
        ),
    )
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "privacy.temporary_audio")
    assert check.severity is Severity.OK
    assert check.code == "temp_audio.ready"


def test_temporary_audio_without_a_runtime_directory_is_an_error(
    tmp_path: Path, credentials: InMemoryCredentialStore
) -> None:
    paths = DesktopPaths.resolve(
        {
            "HOME": str(tmp_path),
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
            "XDG_STATE_HOME": str(tmp_path / "s"),
            "XDG_DATA_HOME": str(tmp_path / "d"),
        }
    )
    assert paths.runtime_dir is None
    save_managed_config(
        paths.config_file,
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            privacy={"temporary_audio_processing": True},
        ),
    )
    report = run_diagnostics(paths.config_file, paths=paths, credentials=credentials)
    check = next(item for item in report.checks if item.check_id == "privacy.temporary_audio")
    assert check.severity is Severity.ERROR
    assert check.code == DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE.value


def test_a_user_confirmed_activation_is_recorded_as_user_confirmed(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    save_managed_config(
        desktop_paths.config_file,
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            client={
                "adapter_id": "demo",
                "display_name": "Demo",
                "server_name": "open-transcribe",
                "activation": "user_confirmed",
            },
        ),
    )
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "client.registration")
    assert check.code == "client.user_confirmed"
    assert "you confirmed" in check.title


def test_running_as_root_is_refused_in_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    report = run_diagnostics()
    check = next(item for item in report.checks if item.check_id == "platform.privilege")
    assert check.severity is Severity.ERROR
    assert check.code == "privilege.root"


def test_a_graphical_session_is_reported_as_such(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    report = run_diagnostics()
    check = next(item for item in report.checks if item.check_id == "platform.session")
    assert check.severity is Severity.OK
    assert report.session_type == "wayland"


def test_the_engine_handshake_check_is_only_run_when_asked(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore, engine_stub: Path
) -> None:
    save_managed_config(
        desktop_paths.config_file, ManagedConfig(schema_version=1, installation_id="0" * 32)
    )
    quiet = run_diagnostics(desktop_paths.config_file, paths=desktop_paths, credentials=credentials)
    assert not any(check.check_id == "engine.handshake" for check in quiet.checks)


# -- the client matrix and adapters --------------------------------------------------------


def test_an_unknown_matrix_version_is_refused(tmp_path: Path) -> None:
    (tmp_path / "desktop").mkdir()
    (tmp_path / "desktop" / "clients.toml").write_text("schema_version = 99\n", encoding="utf-8")
    with pytest.raises(DesktopError) as caught:
        load_matrix(tmp_path)
    assert caught.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED


def test_a_missing_matrix_leaves_only_the_manual_path(tmp_path: Path) -> None:
    assert load_matrix(tmp_path) == []
    adapters = build_adapters(tmp_path, {"HOME": str(tmp_path)})
    assert [adapter.adapter_id for adapter in adapters] == ["manual"]


def test_matrix_paths_that_escape_their_base_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "desktop").mkdir()
    (tmp_path / "desktop" / "clients.toml").write_text(
        "schema_version = 1\n"
        '[[clients]]\nid = "escape"\ndisplay_name = "Escape"\nkind = "json"\n'
        'config_paths = ["$HOME/../../etc/passwd", "relative/path.json"]\n',
        encoding="utf-8",
    )
    adapters = build_adapters(tmp_path, {"HOME": str(tmp_path)})
    assert [adapter.adapter_id for adapter in adapters] == ["manual"]


def test_an_unknown_client_kind_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "desktop").mkdir()
    (tmp_path / "desktop" / "clients.toml").write_text(
        "schema_version = 1\n[[clients]]\n"
        'id = "odd"\ndisplay_name = "Odd"\nkind = "carrier-pigeon"\n',
        encoding="utf-8",
    )
    adapters = build_adapters(tmp_path, {"HOME": str(tmp_path)})
    assert [adapter.adapter_id for adapter in adapters] == ["manual"]


def test_the_manual_path_describes_the_fields_without_a_secret() -> None:
    adapter = ManualRegistrationAdapter()
    registration = ServerRegistration(name="open-transcribe", command=ENGINE, config_path=CONFIG)
    assert adapter.detect()
    assert adapter.inventory() == []
    assert adapter.remove("open-transcribe") is False
    plan = adapter.plan(registration, owned=frozenset(), takeover=False)
    assert plan.target_description.startswith("https://")
    fields = registration.as_fields()
    assert fields["transport"] == "stdio"
    assert fields["command"] == str(ENGINE)
    assert "key" not in json.dumps(fields).lower()


def test_a_client_store_that_uses_our_key_for_something_else_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"mcpServers": "a string"}), encoding="utf-8")
    adapter = JsonMcpServersAdapter(adapter_id="d", display_name="D", config_path=path)
    registration = ServerRegistration(name="open-transcribe", command=ENGINE, config_path=CONFIG)
    assert adapter.inventory() == []
    plan = adapter.plan(registration, owned=frozenset(), takeover=False)
    with pytest.raises(DesktopError) as caught:
        adapter.apply(plan)
    assert caught.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED


def test_an_empty_client_store_is_created_rather_than_rejected(tmp_path: Path) -> None:
    path = tmp_path / "client" / "config.json"
    path.parent.mkdir()
    adapter = JsonMcpServersAdapter(adapter_id="d", display_name="D", config_path=path)
    registration = ServerRegistration(name="open-transcribe", command=ENGINE, config_path=CONFIG)
    assert adapter.detect()
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    assert json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["open-transcribe"]


def test_a_client_store_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    adapter = JsonMcpServersAdapter(adapter_id="d", display_name="D", config_path=path)
    with pytest.raises(DesktopError) as caught:
        adapter.inventory()
    assert caught.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED


def test_an_oversized_client_store_is_never_rewritten(tmp_path: Path) -> None:
    from open_transcribe.desktop.clients.json_store import MAX_CLIENT_CONFIG_BYTES

    path = tmp_path / "client.json"
    path.write_text("{}" + " " * MAX_CLIENT_CONFIG_BYTES, encoding="utf-8")
    adapter = JsonMcpServersAdapter(adapter_id="d", display_name="D", config_path=path)
    with pytest.raises(DesktopError) as caught:
        adapter.inventory()
    assert caught.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED


def test_removal_from_a_store_without_our_entry_reports_nothing_removed(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    adapter = JsonMcpServersAdapter(adapter_id="d", display_name="D", config_path=path)
    assert adapter.remove("open-transcribe") is False
    assert adapter.support_status is SupportStatus.UNTESTED


# -- credentials, journal, installation ------------------------------------------------------


def test_deleting_a_credential_that_is_gone_is_not_an_error() -> None:
    store = InMemoryCredentialStore()
    ref = new_credential_ref("0" * 32, "groq", "api_key")
    assert store.delete(ref) is False
    store.put(ref, SecretStr("k"))
    assert store.delete(ref) is True


def test_a_backend_that_reports_no_such_password_is_not_a_keyring_failure() -> None:
    import keyring.errors

    class _Absent:
        def delete_password(self, service: str, account: str) -> None:
            raise keyring.errors.PasswordDeleteError(account)

    store = SecretServiceCredentialStore(backend=_Absent())
    assert store.delete(new_credential_ref("0" * 32, "groq", "api_key")) is False


def test_a_journal_written_by_a_newer_build_is_refused(desktop_paths: DesktopPaths) -> None:
    write_private_file(
        desktop_paths.journal_file,
        json.dumps({"schema_version": 99, "installation_id": "0" * 32}).encode(),
    )
    with pytest.raises(DesktopError) as caught:
        load_journal(desktop_paths.journal_file, "0" * 32)
    assert caught.value.code is DesktopErrorCode.CONFIG_UNSUPPORTED_VERSION


def test_the_journal_keeps_a_bounded_history(desktop_paths: DesktopPaths) -> None:
    journal = InstallJournal(installation_id="0" * 32)
    for _ in range(300):
        journal.record("client", "applied")
    assert len(journal.phases) == 200


def test_owning_a_resource_twice_replaces_rather_than_duplicates() -> None:
    journal = InstallJournal(installation_id="0" * 32)
    for fingerprint in ("aaa", "bbb"):
        journal.own(
            OwnedResource(
                kind=ResourceKind.CLIENT_REGISTRATION,
                identifier="demo:open-transcribe",
                fingerprint=fingerprint,
            )
        )
    resources = journal.resources(ResourceKind.CLIENT_REGISTRATION)
    assert len(resources) == 1
    assert resources[0].fingerprint == "bbb"
    assert journal.disown(ResourceKind.CLIENT_REGISTRATION, "absent") is None


def test_a_rerun_that_succeeds_clears_an_earlier_failure() -> None:
    journal = InstallJournal(installation_id="0" * 32)
    journal.record("client", "intended")
    journal.record("client", "failed", "CLIENT_CONFLICT")
    assert [phase.name for phase in journal.incomplete] == ["client"]
    journal.record("client", "applied")
    assert journal.incomplete == []


def test_the_engine_path_is_refused_when_the_package_is_not_installed() -> None:
    installation = current_installation()
    if installation.packaged:  # pragma: no cover - only on a machine with the package installed
        pytest.skip("the package is installed here")
    with pytest.raises(DesktopError) as caught:
        engine_executable()
    assert caught.value.code is DesktopErrorCode.ENGINE_MISSING


def test_a_non_executable_engine_is_refused_before_it_is_launched(tmp_path: Path) -> None:
    candidate = tmp_path / "engine"
    candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate.chmod(0o644)
    with pytest.raises(DesktopError) as caught:
        require_executable(candidate)
    assert caught.value.code is DesktopErrorCode.ENGINE_MISSING
    with pytest.raises(DesktopError):
        probe_engine(candidate, CONFIG)


def test_an_engine_that_never_answers_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from open_transcribe.desktop import engine_probe

    monkeypatch.setattr(engine_probe, "HANDSHAKE_TIMEOUT_SECONDS", 1.0)
    silent = tmp_path / "silent-engine"
    silent.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    silent.chmod(0o755)
    config = tmp_path / "config.toml"
    save_managed_config(config, ManagedConfig(schema_version=1, installation_id="0" * 32))
    result = engine_probe.probe_engine(silent, config)
    assert not result.ok
    assert result.reason == "engine.timeout"


def test_the_tool_surface_is_exactly_the_five_public_tools() -> None:
    assert {
        "transcribe_audio",
        "get_transcript_chunk",
        "delete_transcript",
        "list_transcription_models",
        "estimate_transcription_cost",
    } == EXPECTED_TOOLS
