"""The client integration boundary.

Adapters live outside the domain and transcription services. An adapter may read a client's
inventory, propose a plan, register one server, read the result back, and remove what this
installation owns. It may not rewrite a client's configuration wholesale, and it never sees a
credential: a registration describes how to launch the engine, not how to authenticate.
"""

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

DEFAULT_SERVER_NAME = "open-transcribe"


class SupportStatus(StrEnum):
    """How far this build's support for a client has actually been proven."""

    TESTED = "tested"
    """Registration and readback verified against this client version in the release matrix."""

    UNTESTED = "untested"
    """The format is documented but this build has not been tested against it."""

    MANUAL_ONLY = "manual_only"
    """No supported registration API. The user is given the exact fields to enter."""


class Ownership(StrEnum):
    OURS = "ours"
    FOREIGN = "foreign"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ServerRegistration:
    """A secret-free description of how a client must launch the packaged engine."""

    name: str
    command: Path
    config_path: Path

    def __post_init__(self) -> None:
        if not self.command.is_absolute() or not self.config_path.is_absolute():
            raise ValueError("a registration must use absolute paths")

    @property
    def args(self) -> tuple[str, ...]:
        return ("serve", "--transport", "stdio", "--config", str(self.config_path))

    @property
    def argv(self) -> tuple[str, ...]:
        return (str(self.command), *self.args)

    def fingerprint(self) -> str:
        """A stable identity for this exact launch, used to recognize what we registered."""
        return hashlib.sha256("\x00".join(self.argv).encode("utf-8")).hexdigest()[:32]

    def as_fields(self) -> dict[str, object]:
        """The logical fields to show when no automatic path exists."""
        return {"command": str(self.command), "args": list(self.args), "transport": "stdio"}


@dataclass(frozen=True, slots=True)
class ExistingEntry:
    """One MCP server a client already knows about, as observed, not as advertised."""

    name: str
    command: str | None = None
    args: tuple[str, ...] = field(default_factory=tuple)
    ownership: Ownership = Ownership.UNKNOWN

    def fingerprint(self) -> str | None:
        if self.command is None:
            return None
        joined = "\x00".join((self.command, *self.args))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class PlannedAction:
    kind: str
    target: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RegistrationPlan:
    """What would change, shown before anything does."""

    adapter_id: str
    registration: ServerRegistration
    actions: tuple[PlannedAction, ...] = field(default_factory=tuple)
    conflicts: tuple[ExistingEntry, ...] = field(default_factory=tuple)
    takeover: tuple[ExistingEntry, ...] = field(default_factory=tuple)
    target_description: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    @property
    def changes_nothing(self) -> bool:
        return not self.actions


class ClientAdapter(Protocol):
    adapter_id: str
    display_name: str
    support_status: SupportStatus

    def detect(self) -> bool:
        """Bounded discovery. Never a recursive search of the user's home directory."""

    def inventory(self) -> list[ExistingEntry]:
        """Read-only. Discovery alone changes nothing."""

    def plan(
        self, registration: ServerRegistration, *, owned: frozenset[str], takeover: bool
    ) -> RegistrationPlan: ...

    def apply(self, plan: RegistrationPlan) -> None: ...

    def readback(self, name: str) -> ExistingEntry | None: ...

    def remove(self, name: str) -> bool: ...


def classify(
    entry: ExistingEntry, registration: ServerRegistration, owned: frozenset[str]
) -> Ownership:
    """Decide ownership from recorded installations and observed launch details.

    A display name or a substring match is never enough: an entry is ours only if this
    installation recorded it, or if it launches exactly the engine we would register.
    """
    fingerprint = entry.fingerprint()
    if fingerprint is None:
        return Ownership.UNKNOWN
    if fingerprint in owned or fingerprint == registration.fingerprint():
        return Ownership.OURS
    return Ownership.FOREIGN


def parse_argv(value: object) -> tuple[str, ...]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(str(item) for item in value)
    return ()


def dumps_client_json(document: object) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=False) + "\n").encode("utf-8")
