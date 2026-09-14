"""CLI-01 and CLI-03 for a client driven through its own command line."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from open_transcribe.desktop.clients.base import ServerRegistration, SupportStatus
from open_transcribe.desktop.clients.command import CommandLineAdapter
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

ENGINE = Path("/opt/open-transcribe-assistant/open-transcribe-mcp")
CONFIG = Path("/home/user/.config/open-transcribe-mcp/desktop/config.toml")
FAKE_CLIENT = Path(__file__).parent / "fake_client.py"


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "client-store.json"
    path.write_text(
        json.dumps({"mcpServers": {"notes": {"command": "/usr/bin/notes"}}}), encoding="utf-8"
    )
    monkeypatch.setenv("FAKE_CLIENT_STORE", str(path))
    return path


@pytest.fixture
def executable(tmp_path: Path) -> Path:
    path = tmp_path / "fake-client"
    path.write_text(FAKE_CLIENT.read_text(encoding="utf-8"), encoding="utf-8")
    path.chmod(0o755)
    return path


def _passthrough(adapter: CommandLineAdapter):
    """Run the stand-in client with this test's environment so it can find its store.

    The adapter itself runs a client with a minimal environment; that is checked separately in
    `test_the_client_runs_with_a_minimal_environment`.
    """

    def run(argv, *, check):  # type: ignore[no-untyped-def]
        return subprocess.run(  # noqa: S603 - fixed vector, no shell
            [sys.executable, str(adapter.executable), *argv],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
            env=dict(os.environ),
        )

    return run


@pytest.fixture
def adapter(executable: Path, store: Path, monkeypatch: pytest.MonkeyPatch) -> CommandLineAdapter:
    built = CommandLineAdapter(
        adapter_id="fake",
        display_name="Fake client",
        executable=executable,
        add_argv=("mcp", "add", "{name}", "--", "{command}", "{args}"),
        list_argv=("mcp", "list", "--json"),
        remove_argv=("mcp", "remove", "{name}"),
    )
    monkeypatch.setattr(built, "_run", _passthrough(built))
    return built


@pytest.fixture
def registration() -> ServerRegistration:
    return ServerRegistration(name="open-transcribe", command=ENGINE, config_path=CONFIG)


def test_detection_asks_the_installed_command_rather_than_trusting_its_name(
    adapter: CommandLineAdapter,
) -> None:
    assert adapter.detect() is True


def test_a_missing_executable_is_simply_not_detected(tmp_path: Path) -> None:
    absent = CommandLineAdapter(
        adapter_id="gone",
        display_name="Gone",
        executable=tmp_path / "not-here",
        add_argv=(),
        list_argv=("mcp", "list", "--json"),
    )
    assert absent.detect() is False
    assert absent.inventory() == []
    assert absent.readback("open-transcribe") is None


def test_the_client_runs_with_a_minimal_environment(executable: Path, store: Path) -> None:
    """The adapter passes a minimal environment, so a client cannot be steered by exported state."""
    bare = CommandLineAdapter(
        adapter_id="fake",
        display_name="Fake client",
        executable=executable,
        add_argv=(),
        list_argv=("mcp", "list", "--json"),
    )
    # The stand-in needs FAKE_CLIENT_STORE, which the adapter does not pass on, so it fails.
    assert bare.inventory() == []


def test_registration_readback_shows_the_exact_bundled_engine(
    adapter: CommandLineAdapter, registration: ServerRegistration
) -> None:
    plan = adapter.plan(registration, owned=frozenset(), takeover=False)
    assert [action.kind for action in plan.actions] == ["add_server"]
    adapter.apply(plan)

    entry = adapter.readback("open-transcribe")
    assert entry is not None
    assert entry.command == str(ENGINE)
    assert entry.args == registration.args
    assert entry.fingerprint() == registration.fingerprint()


def test_re_running_changes_nothing_and_creates_no_duplicate(
    adapter: CommandLineAdapter, registration: ServerRegistration, store: Path
) -> None:
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    second = adapter.plan(registration, owned=frozenset(), takeover=False)
    assert second.changes_nothing
    adapter.apply(second)
    assert sorted(json.loads(store.read_text(encoding="utf-8"))["mcpServers"]) == [
        "notes",
        "open-transcribe",
    ]


def test_unrelated_servers_survive_registration_and_removal(
    adapter: CommandLineAdapter, registration: ServerRegistration, store: Path
) -> None:
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    assert adapter.remove("open-transcribe") is True
    remaining = json.loads(store.read_text(encoding="utf-8"))["mcpServers"]
    assert sorted(remaining) == ["notes"]
    # Removing something that is not there is reported, not invented.
    assert adapter.remove("open-transcribe") is False


def test_the_arguments_are_a_fixed_vector_with_no_shell_interpolation(
    adapter: CommandLineAdapter, registration: ServerRegistration
) -> None:
    argv = adapter._substitute(adapter.add_argv, registration)
    assert argv == (
        "mcp",
        "add",
        "open-transcribe",
        "--",
        str(ENGINE),
        "serve",
        "--transport",
        "stdio",
        "--config",
        str(CONFIG),
    )
    assert not any(character in item for item in argv for character in ";|&$`")


def test_a_conflict_is_reported_rather_than_overwritten(
    adapter: CommandLineAdapter, registration: ServerRegistration, store: Path
) -> None:
    store.write_text(
        json.dumps({"mcpServers": {"open-transcribe": {"command": "/usr/bin/other"}}}),
        encoding="utf-8",
    )
    plan = adapter.plan(registration, owned=frozenset(), takeover=False)
    assert plan.blocked
    with pytest.raises(DesktopError) as caught:
        adapter.apply(plan)
    assert caught.value.code is DesktopErrorCode.CLIENT_CONFLICT
    current = json.loads(store.read_text(encoding="utf-8"))["mcpServers"]["open-transcribe"]
    assert current["command"] == "/usr/bin/other"


def test_takeover_removes_the_old_entry_before_adding_ours(
    adapter: CommandLineAdapter, registration: ServerRegistration, store: Path
) -> None:
    store.write_text(
        json.dumps({"mcpServers": {"open-transcribe": {"command": "/usr/bin/other"}}}),
        encoding="utf-8",
    )
    plan = adapter.plan(registration, owned=frozenset(), takeover=True)
    assert not plan.blocked
    adapter.apply(plan)
    entry = adapter.readback("open-transcribe")
    assert entry is not None
    assert entry.command == str(ENGINE)


def test_an_entry_this_installation_recorded_is_updated_not_duplicated(
    adapter: CommandLineAdapter, registration: ServerRegistration, store: Path
) -> None:
    store.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "open-transcribe": {
                        "command": str(ENGINE),
                        "args": ["serve", "--transport", "stdio", "--config", "/old.toml"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    known = adapter.inventory()[0].fingerprint() or ""
    plan = adapter.plan(registration, owned=frozenset({known}), takeover=False)
    assert [action.kind for action in plan.actions] == ["update_server"]


def test_an_adapter_without_a_removal_command_blocks_the_operation(
    executable: Path, registration: ServerRegistration, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI-03: no supported removal API means the operation is blocked, never improvised."""
    limited = CommandLineAdapter(
        adapter_id="fake",
        display_name="Fake client",
        executable=executable,
        add_argv=("mcp", "add", "{name}", "--", "{command}", "{args}"),
        list_argv=("mcp", "list", "--json"),
        remove_argv=None,
    )
    monkeypatch.setattr(limited, "_run", _passthrough(limited))
    with pytest.raises(DesktopError) as caught:
        limited.remove("open-transcribe")
    assert caught.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED
    assert "open-transcribe" in (caught.value.recovery or "")


def test_a_refused_registration_is_reported_with_a_manual_path(
    adapter: CommandLineAdapter, registration: ServerRegistration, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = adapter.plan(registration, owned=frozenset(), takeover=False)
    monkeypatch.setattr(adapter, "_run", lambda argv, *, check: None)
    with pytest.raises(DesktopError) as caught:
        adapter.apply(plan)
    assert caught.value.code is DesktopErrorCode.CLIENT_REGISTRATION_FAILED
    assert "manually" in (caught.value.recovery or "")


def test_unparseable_client_output_yields_no_ownership_claims(
    adapter: CommandLineAdapter,
) -> None:
    """Guessing at a human-readable table would invent ownership facts."""
    from open_transcribe.desktop.clients.command import MAX_COMMAND_OUTPUT_BYTES, _parse_listing

    assert _parse_listing("NAME   COMMAND\nnotes  /usr/bin/notes") == []
    assert _parse_listing("x" * (MAX_COMMAND_OUTPUT_BYTES + 1)) == []
    assert _parse_listing(json.dumps({"mcpServers": "not-a-mapping"})) == []
    assert adapter.support_status is SupportStatus.UNTESTED
