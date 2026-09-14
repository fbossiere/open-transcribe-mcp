"""SEC-09 and PKG-03: the diagnostic export, and the command line's existing behaviour."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from open_transcribe.cli import build_parser, run_cli
from open_transcribe.desktop.credentials import InMemoryCredentialStore, new_credential_ref
from open_transcribe.desktop.diagnostics import Severity, run_diagnostics
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.schema import ManagedConfig
from open_transcribe.desktop.store import save_managed_config

FORBIDDEN_IN_EXPORT = (
    "api_key",
    "secret",
    "Bearer",
    "/home/",
    "https://",
    "transcript",
)


def _write(paths: DesktopPaths, config: ManagedConfig) -> Path:
    save_managed_config(paths.config_file, config)
    return paths.config_file


def test_a_missing_setup_is_information_not_an_error(desktop_paths: DesktopPaths) -> None:
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=InMemoryCredentialStore()
    )
    load = next(check for check in report.checks if check.check_id == "config.load")
    assert load.severity is Severity.INFO
    assert load.code == "CONFIG_MISSING"


def test_a_saved_setup_without_an_enabled_provider_is_an_error(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    _write(desktop_paths, ManagedConfig(schema_version=1, installation_id="0" * 32))
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "providers.enabled")
    assert check.severity is Severity.ERROR
    assert check.recovery is not None


def test_a_missing_key_is_reported_as_missing(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    ref = new_credential_ref("0" * 32, "groq", "api_key")
    _write(
        desktop_paths,
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            providers={"groq": {"enabled": True, "credentials": {"api_key": ref.model_dump()}}},
        ),
    )
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "providers.credentials")
    assert check.severity is Severity.ERROR
    assert check.code == "credential.missing"

    credentials.put(ref, SecretStr("k"))
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "providers.credentials")
    assert check.severity is Severity.OK


def test_a_saved_key_is_never_reported_as_verified(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    ref = new_credential_ref("0" * 32, "groq", "api_key")
    credentials.put(ref, SecretStr("k"))
    _write(
        desktop_paths,
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            providers={"groq": {"enabled": True, "credentials": {"api_key": ref.model_dump()}}},
        ),
    )
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "providers.verified")
    assert check.title == "Key saved — transcription not tested"


def test_a_registration_is_never_reported_as_active_on_its_own(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    _write(
        desktop_paths,
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            client={"adapter_id": "demo", "display_name": "Demo", "server_name": "open-transcribe"},
        ),
    )
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    check = next(item for item in report.checks if item.check_id == "client.registration")
    assert check.title == "Connection saved — check it in your assistant"


def test_the_export_carries_only_allowlisted_fields(
    desktop_paths: DesktopPaths, credentials: InMemoryCredentialStore
) -> None:
    ref = new_credential_ref("0" * 32, "groq", "api_key")
    _write(
        desktop_paths,
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            providers={
                "groq": {"enabled": True, "credentials": {"api_key": ref.model_dump()}},
                "microsoft": {
                    "enabled": False,
                    "endpoint": "https://private-resource.example.com",
                },
            },
        ),
    )
    report = run_diagnostics(
        desktop_paths.config_file, paths=desktop_paths, credentials=credentials
    )
    exported = json.dumps(report.to_export())

    assert set(json.loads(exported)) == {
        "schema",
        "generated_at",
        "application_version",
        "os_release",
        "session_type",
        "worst_severity",
        "checks",
    }
    for check in json.loads(exported)["checks"]:
        assert set(check) == {"id", "severity", "code"}
    for forbidden in FORBIDDEN_IN_EXPORT:
        assert forbidden not in exported
    assert ref.account not in exported
    assert "private-resource" not in exported
    # Local detail exists for the user to expand, and stays out of the export.
    assert any(check.detail for check in report.checks)


def test_the_bare_entry_point_still_starts_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """PKG-03: an existing CLI installation keeps its original behaviour."""
    started: list[str] = []
    monkeypatch.setattr(
        "open_transcribe.server.serve_http", lambda settings: started.append(settings.transport)
    )
    monkeypatch.setattr("open_transcribe.settings.get_settings", lambda: _http_settings())
    assert run_cli([]) == 0
    assert started == ["http"]


def _http_settings():
    from open_transcribe.settings import Settings

    return Settings(_env_file=None, security={"auth_mode": "bearer", "bearer_token": "t"})


def test_stdio_requires_an_explicit_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_cli(["serve", "--transport", "stdio"]) == 2
    assert "--config" in capsys.readouterr().err


def test_http_refuses_a_managed_configuration(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert run_cli(["serve", "--transport", "http", "--config", str(tmp_path / "c.toml")]) == 2
    assert "stdio" in capsys.readouterr().err


def test_doctor_emits_the_typed_report_as_json(
    desktop_paths: DesktopPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(desktop_paths, ManagedConfig(schema_version=1, installation_id="0" * 32))
    code = run_cli(["doctor", "--config", str(desktop_paths.config_file), "--json"])
    document = json.loads(capsys.readouterr().out)
    assert document["schema"] == "open-transcribe-diagnostic/1"
    assert code in {0, 1}


def test_doctor_is_not_an_mcp_tool() -> None:
    from open_transcribe.desktop.engine_probe import EXPECTED_TOOLS

    assert "doctor" not in EXPECTED_TOOLS
    assert not any("config" in name or "client" in name for name in EXPECTED_TOOLS)


def test_cleanup_is_quiet_when_the_installation_is_gone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A leftover timer must stay harmless after the package is removed."""
    assert run_cli(["cleanup-temporary-audio", "--config", str(tmp_path / "gone.toml")]) == 0
    assert "CONFIG_MISSING" in capsys.readouterr().err


def test_the_parser_exposes_only_administration_commands() -> None:
    import argparse

    actions = [
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert sorted(actions[0].choices) == ["cleanup-temporary-audio", "doctor", "serve"]


def test_the_engine_runs_without_the_project_checkout_on_the_path(
    engine_stub: Path, tmp_path: Path
) -> None:
    """PKG-04/PKG-05: the engine starts from a bare environment and downloads nothing."""
    config = tmp_path / "config.toml"
    save_managed_config(config, ManagedConfig(schema_version=1, installation_id="0" * 32))
    result = subprocess.run(  # noqa: S603 - fixed vector, no shell
        [str(engine_stub), "doctor", "--config", str(config), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd="/",
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode in {0, 1}, result.stderr
    assert json.loads(result.stdout)["schema"] == "open-transcribe-diagnostic/1"


def test_python_module_entry_point_matches_the_console_script() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "open_transcribe", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "serve" in result.stdout
