"""SEC-04 and USE-01: the local transport, its authentication boundary, and stream discipline."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from open_transcribe.desktop.engine_probe import (
    EXPECTED_TOOLS,
    engine_command,
    probe_engine,
)
from open_transcribe.desktop.schema import ManagedConfig
from open_transcribe.desktop.store import save_managed_config
from open_transcribe.settings import ExplicitSettings, Settings

PROTOCOL_VERSION = "2025-06-18"


@pytest.fixture
def managed_config_file(tmp_path: Path, managed_config: ManagedConfig) -> Path:
    path = tmp_path / "desktop" / "config.toml"
    save_managed_config(path, managed_config)
    return path


def test_the_registration_command_is_a_fixed_absolute_vector(
    engine_stub: Path, managed_config_file: Path
) -> None:
    command = engine_command(engine_stub, managed_config_file)
    assert command[0] == str(engine_stub)
    assert command[1:] == ["serve", "--transport", "stdio", "--config", str(managed_config_file)]
    assert all(Path(item).is_absolute() for item in (command[0], command[-1]))


def test_the_packaged_engine_answers_with_exactly_the_expected_tools(
    engine_stub: Path, managed_config_file: Path
) -> None:
    result = probe_engine(engine_stub, managed_config_file)
    assert result.ok, result.reason
    assert set(result.tools) == EXPECTED_TOOLS
    assert result.unexpected_tools == ()
    assert result.missing_tools == ()


def test_an_engine_offering_other_tools_is_rejected(
    tmp_path: Path, managed_config_file: Path
) -> None:
    """A swapped engine is a failure, not something to accept quietly."""
    impostor = tmp_path / "impostor"
    impostor.write_text(
        "#!/bin/sh\n"
        f'PYTHONPATH="{Path(__file__).resolve().parents[2] / "src"}:'
        f'{os.environ.get("PYTHONPATH", "")}" '
        f'exec "{sys.executable}" -c "{_IMPOSTOR_SOURCE}"\n',
        encoding="utf-8",
    )
    impostor.chmod(0o755)
    result = probe_engine(impostor, managed_config_file)
    assert not result.ok
    assert "run_arbitrary_command" in result.unexpected_tools


_IMPOSTOR_SOURCE = (
    "from fastmcp import FastMCP;"
    "m = FastMCP('OpenTranscribe');"
    "m.tool(lambda: 'pwned', name='run_arbitrary_command');"
    "m.run(transport='stdio', show_banner=False)"
)


def _read_message(process: subprocess.Popen[str]) -> dict[str, object]:
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line.strip(), "the engine closed stdout without answering"
    return json.loads(line)


def test_stdio_opens_no_listening_socket_and_keeps_stdout_clean(
    engine_stub: Path, managed_config_file: Path
) -> None:
    process = subprocess.Popen(  # noqa: S603 - fixed vector, no shell
        engine_command(engine_stub, managed_config_file),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdin is not None
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "acceptance", "version": "0"},
            },
        }
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        response = _read_message(process)
        assert response["id"] == 1
        assert "result" in response, response

        # The event loop's own self-pipe is a socketpair, so the requirement is not "no socket"
        # but "no network socket": nothing this process owns may appear in the kernel's TCP
        # tables, listening or otherwise.
        network = _network_sockets(process.pid)
        assert network == [], f"the stdio engine opened network sockets: {network}"

        process.stdin.close()
        assert process.wait(timeout=30) == 0
        remainder = process.stdout.read() if process.stdout else ""
    finally:
        if process.poll() is None:  # pragma: no cover - only on an unexpected hang
            process.kill()
            process.wait(timeout=10)
    for line in remainder.splitlines():
        if line.strip():
            json.loads(line)  # stdout carries MCP messages only


def _socket_inodes(pid: int) -> set[str]:
    directory = Path(f"/proc/{pid}/fd")
    if not directory.is_dir():  # pragma: no cover - non-Linux
        pytest.skip("descriptor inspection needs /proc")
    inodes = set()
    for entry in directory.iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[len("socket:[") : -1])
    return inodes


def _network_sockets(pid: int) -> list[str]:
    """Every TCP endpoint the process owns, by matching its descriptors to the kernel tables."""
    inodes = _socket_inodes(pid)
    found = []
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:  # pragma: no cover - restricted /proc
            continue
        for line in lines:
            fields = line.split()
            if len(fields) > 9 and fields[9] in inodes:
                found.append(f"{table}:{fields[1]} state={fields[3]}")
    return found


def test_closing_the_pipe_stops_the_engine(engine_stub: Path, managed_config_file: Path) -> None:
    """The client owns the process: EOF ends it, and no detached daemon is left behind."""
    process = subprocess.Popen(  # noqa: S603 - fixed vector, no shell
        engine_command(engine_stub, managed_config_file),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert process.stdin is not None
    deadline = time.monotonic() + 30
    process.stdin.close()
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() == 0


def test_stdio_settings_refuse_a_network_credential() -> None:
    with pytest.raises(ValueError, match="local session"):
        ExplicitSettings(
            transport="stdio", security={"auth_mode": "bearer", "bearer_token": "secret"}
        )


def test_http_authentication_is_unchanged() -> None:
    """The local transport is a separate case, never a relaxation of the remote one."""
    with pytest.raises(ValueError, match="BEARER_TOKEN"):
        Settings(_env_file=None, transport="http", security={"auth_mode": "bearer"})
    with pytest.raises(ValueError, match="unauthenticated HTTP"):
        Settings(
            _env_file=None, transport="http", environment="prod", security={"auth_mode": "none"}
        )


def test_the_http_application_refuses_to_be_built_from_stdio_settings() -> None:
    from open_transcribe.server import create_app

    settings = ExplicitSettings(transport="stdio", security={"auth_mode": "none"})
    with pytest.raises(ValueError, match="transport"):
        create_app(settings)
