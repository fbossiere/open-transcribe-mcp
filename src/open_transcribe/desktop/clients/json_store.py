"""An adapter for clients that keep MCP servers in a JSON configuration file.

It reads and rewrites exactly one entry. Every other key in the document, including servers the
user or another project registered, is preserved byte-for-byte in value and order.
"""

import json
import os
import stat
from pathlib import Path

from open_transcribe.desktop.clients.base import (
    ExistingEntry,
    Ownership,
    PlannedAction,
    RegistrationPlan,
    ServerRegistration,
    SupportStatus,
    classify,
    dumps_client_json,
    parse_argv,
)
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

MAX_CLIENT_CONFIG_BYTES = 4 * 1024 * 1024


class JsonMcpServersAdapter:
    """Register one server in a JSON document under a configurable key path."""

    def __init__(
        self,
        *,
        adapter_id: str,
        display_name: str,
        config_path: Path,
        key_path: tuple[str, ...] = ("mcpServers",),
        support_status: SupportStatus = SupportStatus.UNTESTED,
        restart_required: bool = True,
    ) -> None:
        self.adapter_id = adapter_id
        self.display_name = display_name
        self.config_path = config_path
        self.key_path = key_path
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
        document = self._read()
        servers = self._servers(document, create=True)
        servers[plan.registration.name] = {
            "command": str(plan.registration.command),
            "args": list(plan.registration.args),
        }
        self._write(document)

    def readback(self, name: str) -> ExistingEntry | None:
        return next((entry for entry in self.inventory() if entry.name == name), None)

    def remove(self, name: str) -> bool:
        document = self._read()
        servers = self._servers(document)
        if name not in servers:
            return False
        del servers[name]
        self._write(document)
        return True

    def _read(self) -> dict[str, object]:
        try:
            info = self.config_path.lstat()
        except FileNotFoundError:
            return {}
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
        raw = self.config_path.read_bytes()
        if not raw.strip():
            return {}
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise DesktopError(
                DesktopErrorCode.CLIENT_UNSUPPORTED,
                f"{self.display_name}'s configuration is not valid JSON.",
                recovery=(
                    "Fix or remove that file in your client, then repair the connection. "
                    "OpenTranscribe will not rewrite a file it cannot read."
                ),
            ) from exc
        if not isinstance(document, dict):
            raise DesktopError(
                DesktopErrorCode.CLIENT_UNSUPPORTED,
                f"{self.display_name}'s configuration has an unexpected shape.",
            )
        return document

    def _servers(self, document: dict[str, object], *, create: bool = False) -> dict[str, object]:
        node: dict[str, object] = document
        for key in self.key_path:
            child = node.get(key)
            if child is None and create:
                child = {}
                node[key] = child
            if not isinstance(child, dict):
                if create:
                    raise DesktopError(
                        DesktopErrorCode.CLIENT_UNSUPPORTED,
                        f"{self.display_name}'s configuration uses '{key}' for something else.",
                    )
                return {}
            node = child
        return node

    def _write(self, document: dict[str, object]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o600
        if self.config_path.is_file():
            mode = stat.S_IMODE(self.config_path.stat().st_mode)
        temp = self.config_path.with_name(f".{self.config_path.name}.open-transcribe.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(dumps_client_json(document))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, mode)
            os.replace(temp, self.config_path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
