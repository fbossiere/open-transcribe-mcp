"""An adapter that drives a client's own supported CLI.

Arguments are a fixed array with placeholders substituted as whole elements. There is no shell,
no interpolation, and no path built from client output. Output is bounded and treated as
untrusted data: it is parsed for a readback result and redacted before it is ever displayed.
"""

import json
import subprocess
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

COMMAND_TIMEOUT_SECONDS = 30
MAX_COMMAND_OUTPUT_BYTES = 256 * 1024


class CommandLineAdapter:
    """Register through a client command, when the installed command actually supports it."""

    def __init__(
        self,
        *,
        adapter_id: str,
        display_name: str,
        executable: Path | None,
        add_argv: tuple[str, ...],
        list_argv: tuple[str, ...],
        remove_argv: tuple[str, ...] | None = None,
        support_status: SupportStatus = SupportStatus.UNTESTED,
        restart_required: bool = True,
    ) -> None:
        self.adapter_id = adapter_id
        self.display_name = display_name
        self.executable = executable
        self.add_argv = add_argv
        self.list_argv = list_argv
        self.remove_argv = remove_argv
        self.support_status = support_status
        self.restart_required = restart_required

    def detect(self) -> bool:
        """The command must exist and answer its own listing verb.

        A version number, a binary name, or an installation path is not evidence of support.
        """
        if self.executable is None or not self.executable.is_file():
            return False
        result = self._run(self.list_argv, check=False)
        return result is not None and result.returncode == 0

    def inventory(self) -> list[ExistingEntry]:
        result = self._run(self.list_argv, check=False)
        if result is None or result.returncode != 0:
            return []
        return _parse_listing(result.stdout)

    def plan(
        self, registration: ServerRegistration, *, owned: frozenset[str], takeover: bool
    ) -> RegistrationPlan:
        existing = {entry.name: entry for entry in self.inventory()}
        current = existing.get(registration.name)
        conflicts: list[ExistingEntry] = []
        takeovers: list[ExistingEntry] = []
        actions: list[PlannedAction] = []
        if current is None:
            actions.append(PlannedAction("add_server", registration.name, self.display_name))
        elif classify(current, registration, owned) is Ownership.OURS:
            if current.fingerprint() != registration.fingerprint():
                actions.append(PlannedAction("update_server", registration.name, self.display_name))
        elif takeover and self.remove_argv is not None:
            takeovers.append(current)
            actions.append(PlannedAction("replace_server", registration.name, self.display_name))
        else:
            conflicts.append(current)
        return RegistrationPlan(
            adapter_id=self.adapter_id,
            registration=registration,
            actions=tuple(actions),
            conflicts=tuple(conflicts),
            takeover=tuple(takeovers),
            target_description=self.display_name,
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
        if plan.takeover:
            self.remove(plan.registration.name)
        argv = self._substitute(self.add_argv, plan.registration)
        result = self._run(argv, check=False)
        if result is None or result.returncode != 0:
            raise DesktopError(
                DesktopErrorCode.CLIENT_REGISTRATION_FAILED,
                f"{self.display_name} did not accept the registration.",
                recovery="Open Details for the exact fields, and add the server manually.",
            )

    def readback(self, name: str) -> ExistingEntry | None:
        return next((entry for entry in self.inventory() if entry.name == name), None)

    def remove(self, name: str) -> bool:
        if self.remove_argv is None:
            raise DesktopError(
                DesktopErrorCode.CLIENT_UNSUPPORTED,
                f"{self.display_name} offers no supported removal command.",
                recovery=f"Remove the '{name}' server from that client yourself.",
            )
        argv = tuple(item.replace("{name}", name) for item in self.remove_argv)
        result = self._run(argv, check=False)
        return result is not None and result.returncode == 0

    def _substitute(
        self, template: tuple[str, ...], registration: ServerRegistration
    ) -> tuple[str, ...]:
        replacements = {
            "{name}": registration.name,
            "{command}": str(registration.command),
            "{config}": str(registration.config_path),
        }
        argv: list[str] = []
        for item in template:
            if item == "{args}":
                argv.extend(registration.args)
                continue
            argv.append(replacements.get(item, item))
        return tuple(argv)

    def _run(
        self, argv: tuple[str, ...], *, check: bool
    ) -> "subprocess.CompletedProcess[str] | None":
        if self.executable is None:
            return None
        try:
            return subprocess.run(  # noqa: S603 - fixed vector, absolute executable, no shell
                [str(self.executable), *argv],
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=check,
                shell=False,
                env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
            )
        except (OSError, subprocess.SubprocessError):
            return None


def _parse_listing(stdout: str) -> list[ExistingEntry]:
    """Read a JSON listing if the client produced one, and otherwise report nothing.

    Guessing at a human-readable table would invent ownership facts; an empty inventory is the
    honest answer, and the caller shows the manual path instead.
    """
    if len(stdout.encode("utf-8", "replace")) > MAX_COMMAND_OUTPUT_BYTES:
        return []
    try:
        document = json.loads(stdout)
    except ValueError:
        return []
    servers = document.get("mcpServers") if isinstance(document, dict) else None
    if not isinstance(servers, dict):
        return []
    return [
        ExistingEntry(
            name=str(name),
            command=value.get("command") if isinstance(value, dict) else None,
            args=parse_argv(value.get("args")) if isinstance(value, dict) else (),
        )
        for name, value in servers.items()
    ]
