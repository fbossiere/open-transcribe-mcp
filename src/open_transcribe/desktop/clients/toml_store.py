"""An adapter for clients that keep MCP servers in a TOML configuration file.

The ChatGPT desktop app reads the Codex host's `config.toml`, so the file this adapter edits is
a file the user also maintains by hand. Re-serializing the document would silently drop their
comments and formatting, so only the one table this installation owns is rewritten, in place.
Every other byte of the file is left exactly as it was found.
"""

import os
import re
import stat
import tomllib
from pathlib import Path

from open_transcribe.desktop.clients.base import (
    ExistingEntry,
    Ownership,
    PlannedAction,
    RegistrationPlan,
    ServerRegistration,
    SupportStatus,
    classify,
    parse_argv,
)
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

MAX_CLIENT_CONFIG_BYTES = 4 * 1024 * 1024

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def quote_key(name: str) -> str:
    """A bare key where TOML allows one, and a quoted key where it does not."""
    if _BARE_KEY.match(name):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def quote_value(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


class TomlMcpServersAdapter:
    """Register one server as a TOML table under a configurable table path."""

    def __init__(
        self,
        *,
        adapter_id: str,
        display_name: str,
        config_path: Path,
        table_path: tuple[str, ...] = ("mcp_servers",),
        support_status: SupportStatus = SupportStatus.UNTESTED,
        restart_required: bool = True,
    ) -> None:
        self.adapter_id = adapter_id
        self.display_name = display_name
        self.config_path = config_path
        self.table_path = table_path
        self.support_status = support_status
        self.restart_required = restart_required

    def detect(self) -> bool:
        """Present when its configuration file or its parent directory exists. Nothing deeper."""
        return self.config_path.is_file() or self.config_path.parent.is_dir()

    def inventory(self) -> list[ExistingEntry]:
        servers = self._servers(self._read())
        return [
            ExistingEntry(
                name=name,
                command=value.get("command") if isinstance(value, dict) else None,
                args=parse_argv(value.get("args")) if isinstance(value, dict) else (),
            )
            for name, value in servers.items()
        ]

    def plan(
        self, registration: ServerRegistration, *, owned: frozenset[str], takeover: bool
    ) -> RegistrationPlan:
        existing = {entry.name: entry for entry in self.inventory()}
        current = existing.get(registration.name)
        conflicts: list[ExistingEntry] = []
        takeovers: list[ExistingEntry] = []
        actions: list[PlannedAction] = []
        if current is None:
            actions.append(PlannedAction("add_server", registration.name, str(self.config_path)))
        else:
            ownership = classify(current, registration, owned)
            if ownership is Ownership.OURS:
                if current.fingerprint() != registration.fingerprint():
                    actions.append(
                        PlannedAction("update_server", registration.name, str(self.config_path))
                    )
            elif takeover:
                takeovers.append(current)
                actions.append(
                    PlannedAction("replace_server", registration.name, str(self.config_path))
                )
            else:
                # A registration this installation does not own is a conflict, not something to
                # overwrite, and not a reason to quietly create a second server beside it.
                conflicts.append(current)
        return RegistrationPlan(
            adapter_id=self.adapter_id,
            registration=registration,
            actions=tuple(actions),
            conflicts=tuple(conflicts),
            takeover=tuple(takeovers),
            target_description=str(self.config_path),
        )

    def apply(self, plan: RegistrationPlan) -> None:
        if plan.blocked:
            raise DesktopError(
                DesktopErrorCode.CLIENT_CONFLICT,
                f"{self.display_name} already has a server named {plan.registration.name} that "
                "this installation did not create.",
                recovery="Choose to take it over, or rename the existing entry in your client.",
            )
        if plan.changes_nothing:
            return
        text = self._text()
        self._read_text(text)  # Never edit a file this build cannot parse.
        self._write(_replace_table(text, self._header(plan.registration.name), self._table(plan)))

    def readback(self, name: str) -> ExistingEntry | None:
        return next((entry for entry in self.inventory() if entry.name == name), None)

    def remove(self, name: str) -> bool:
        text = self._text()
        if name not in self._servers(self._read_text(text)):
            return False
        self._write(_replace_table(text, self._header(name), None))
        return True

    # -- the one table this installation owns ----------------------------------------

    def _header(self, name: str) -> str:
        return ".".join(quote_key(part) for part in (*self.table_path, name))

    def _table(self, plan: RegistrationPlan) -> str:
        args = "".join(f"  {quote_value(item)},\n" for item in plan.registration.args)
        return (
            f"[{self._header(plan.registration.name)}]\n"
            f"command = {quote_value(str(plan.registration.command))}\n"
            f"args = [\n{args}]\n"
        )

    # -- reading ---------------------------------------------------------------------

    def _text(self) -> str:
        try:
            info = self.config_path.lstat()
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise DesktopError(
                DesktopErrorCode.CLIENT_REGISTRATION_FAILED,
                f"{self.display_name}'s configuration could not be read.",
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise DesktopError(
                DesktopErrorCode.CLIENT_UNSUPPORTED,
                f"{self.display_name}'s configuration is a symbolic link.",
                recovery="Register OpenTranscribe manually in that client instead.",
            )
        if info.st_size > MAX_CLIENT_CONFIG_BYTES:
            raise DesktopError(
                DesktopErrorCode.CLIENT_UNSUPPORTED,
                f"{self.display_name}'s configuration is larger than this build will rewrite.",
                recovery="Register OpenTranscribe manually in that client instead.",
            )
        try:
            return self.config_path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DesktopError(
                DesktopErrorCode.CLIENT_UNSUPPORTED,
                f"{self.display_name}'s configuration is not valid UTF-8.",
                recovery=(
                    "Fix or remove that file in your client, then repair the connection. "
                    "OpenTranscribe will not rewrite a file it cannot read."
                ),
            ) from exc

    def _read(self) -> dict[str, object]:
        return self._read_text(self._text())

    def _read_text(self, text: str) -> dict[str, object]:
        if not text.strip():
            return {}
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise DesktopError(
                DesktopErrorCode.CLIENT_UNSUPPORTED,
                f"{self.display_name}'s configuration is not valid TOML.",
                recovery=(
                    "Fix or remove that file in your client, then repair the connection. "
                    "OpenTranscribe will not rewrite a file it cannot read."
                ),
            ) from exc

    def _servers(self, document: dict[str, object]) -> dict[str, object]:
        node: dict[str, object] = document
        for key in self.table_path:
            child = node.get(key)
            if not isinstance(child, dict):
                return {}
            node = child
        return node

    # -- writing ---------------------------------------------------------------------

    def _write(self, text: str) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o600
        if self.config_path.is_file():
            mode = stat.S_IMODE(self.config_path.stat().st_mode)
        temp = self.config_path.with_name(f".{self.config_path.name}.open-transcribe.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(text.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, mode)
            os.replace(temp, self.config_path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise


def _table_bounds(text: str, header: str) -> tuple[int, int] | None:
    """Locate one table by its header line, from that line to the next header or the end."""
    pattern = re.compile(rf"^[ \t]*\[[ \t]*{re.escape(header)}[ \t]*\][ \t]*$", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        return None
    following = re.compile(r"^[ \t]*\[", re.MULTILINE).search(text, match.end())
    return match.start(), following.start() if following else len(text)


def _replace_table(text: str, header: str, table: str | None) -> str:
    """Swap exactly one table for another, or drop it. Everything else is untouched."""
    bounds = _table_bounds(text, header)
    if bounds is None:
        if table is None:
            return text
        separator = (
            "" if not text or text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
        )
        return f"{text}{separator}{table}"
    start, end = bounds
    return f"{text[:start]}{table or ''}{text[end:]}"
