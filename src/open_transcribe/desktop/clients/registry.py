"""Building client adapters from the packaged compatibility matrix.

The matrix is shipped with this package and pinned to it. Setup assets are never fetched from a
moving branch, and discovery is limited to the exact locations an entry names.
"""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from open_transcribe.desktop.clients.base import ClientAdapter, SupportStatus
from open_transcribe.desktop.clients.command import CommandLineAdapter
from open_transcribe.desktop.clients.json_store import JsonMcpServersAdapter
from open_transcribe.desktop.clients.manual import ManualRegistrationAdapter
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

MATRIX_FILENAME = "clients.toml"
MATRIX_SCHEMA_VERSION = 1


def matrix_path(config_dir: Path) -> Path:
    return config_dir / "desktop" / MATRIX_FILENAME


def load_matrix(config_dir: Path) -> list[dict[str, Any]]:
    path = matrix_path(config_dir)
    if not path.is_file():
        return []
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != MATRIX_SCHEMA_VERSION:
        raise DesktopError(
            DesktopErrorCode.CLIENT_UNSUPPORTED,
            "The packaged client compatibility matrix has an unexpected version.",
            recovery="Reinstall the OpenTranscribe Setup package.",
        )
    clients = document.get("clients", [])
    return [item for item in clients if isinstance(item, dict)]


def build_adapters(
    config_dir: Path, environ: Mapping[str, str] | None = None
) -> list[ClientAdapter]:
    """Return every adapter this build knows about, with the manual path always last."""
    env = environ if environ is not None else os.environ
    adapters: list[ClientAdapter] = []
    for entry in load_matrix(config_dir):
        adapter = _build(entry, env)
        if adapter is not None:
            adapters.append(adapter)
    adapters.append(ManualRegistrationAdapter())
    return adapters


def _build(entry: dict[str, Any], env: Mapping[str, str]) -> ClientAdapter | None:
    kind = entry.get("kind")
    status = SupportStatus(str(entry.get("support_status", "untested")))
    restart = bool(entry.get("restart_required", True))
    if kind == "json":
        path = _first_existing(entry.get("config_paths", []), env)
        if path is None:
            return None
        return JsonMcpServersAdapter(
            adapter_id=str(entry["id"]),
            display_name=str(entry["display_name"]),
            config_path=path,
            key_path=tuple(str(item) for item in entry.get("key_path", ("mcpServers",))),
            support_status=status,
            restart_required=restart,
        )
    if kind == "command":
        executable = _first_existing(entry.get("executables", []), env, require_file=True)
        if executable is None:
            return None
        remove = entry.get("remove_argv")
        return CommandLineAdapter(
            adapter_id=str(entry["id"]),
            display_name=str(entry["display_name"]),
            executable=executable,
            add_argv=tuple(str(item) for item in entry.get("add_argv", ())),
            list_argv=tuple(str(item) for item in entry.get("list_argv", ())),
            remove_argv=tuple(str(item) for item in remove) if remove else None,
            support_status=status,
            restart_required=restart,
        )
    return None


def _first_existing(
    candidates: list[Any], env: Mapping[str, str], *, require_file: bool = False
) -> Path | None:
    """Expand a bounded candidate list. No recursive search, and no traversal outside it."""
    for candidate in candidates:
        expanded = _expand(str(candidate), env)
        if expanded is None:
            continue
        if expanded.is_file():
            return expanded
        if require_file:
            continue
        # A client's own directory existing is evidence it is installed. The home directory
        # existing is not, so a dotfile candidate counts only once the file itself is there.
        home = env.get("HOME")
        if expanded.parent.is_dir() and (home is None or expanded.parent != Path(home)):
            return expanded
    return None


def _expand(value: str, env: Mapping[str, str]) -> Path | None:
    home = env.get("HOME")
    config_home = env.get("XDG_CONFIG_HOME") or (f"{home}/.config" if home else None)
    replacements = {"$HOME": home, "$XDG_CONFIG_HOME": config_home}
    for name, replacement in replacements.items():
        if value.startswith(name):
            if not replacement:
                return None
            value = replacement + value[len(name) :]
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        return None
    return path
