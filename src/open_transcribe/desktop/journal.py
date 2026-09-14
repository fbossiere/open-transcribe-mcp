"""The ownership and recovery journal.

The configuration file, the keyring, and a client's own store do not share a transaction manager.
This journal is what makes an interrupted operation recoverable: it records what was intended and
what was observed to complete, so a rerun can reconcile rather than guess. It holds references,
fingerprints, and normalized outcome codes; never a secret, a URL, or a transcript.
"""

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.paths import read_private_file, write_private_file

JOURNAL_SCHEMA_VERSION = 1


class ResourceKind(StrEnum):
    CONFIG = "config"
    CREDENTIAL = "credential"
    CLIENT_REGISTRATION = "client_registration"
    CLIENT_ASSET = "client_asset"
    CLEANUP_TIMER = "cleanup_timer"
    TEMPORARY_AUDIO_AREA = "temporary_audio_area"


PhaseState = Literal["intended", "applied", "failed", "compensated"]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OwnedResource(Closed):
    """Something this installation created and may therefore remove."""

    kind: ResourceKind
    identifier: str = Field(max_length=512)
    fingerprint: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PhaseRecord(Closed):
    name: str = Field(max_length=64)
    state: PhaseState
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    outcome_code: str | None = Field(default=None, max_length=64)


class InstallJournal(Closed):
    schema_version: int = JOURNAL_SCHEMA_VERSION
    installation_id: str
    application_version: str | None = None
    phases: list[PhaseRecord] = Field(default_factory=list)
    owned: list[OwnedResource] = Field(default_factory=list)
    pending_cleanup: list[OwnedResource] = Field(default_factory=list)

    def record(self, name: str, state: PhaseState, outcome_code: str | None = None) -> None:
        self.phases.append(PhaseRecord(name=name, state=state, outcome_code=outcome_code))
        del self.phases[:-200]

    def own(self, resource: OwnedResource) -> None:
        self.disown(resource.kind, resource.identifier)
        self.owned.append(resource)

    def disown(self, kind: ResourceKind, identifier: str) -> OwnedResource | None:
        for index, item in enumerate(self.owned):
            if item.kind == kind and item.identifier == identifier:
                return self.owned.pop(index)
        return None

    def owns(self, kind: ResourceKind, identifier: str) -> bool:
        return any(item.kind == kind and item.identifier == identifier for item in self.owned)

    def resources(self, kind: ResourceKind) -> list[OwnedResource]:
        return [item for item in self.owned if item.kind == kind]

    @property
    def incomplete(self) -> list[PhaseRecord]:
        """Phases that were intended but never observed to finish, most recent record first.

        A phase is settled by its own latest record, so a run that failed and then succeeded on
        a rerun is complete, and one that succeeded and then failed is not.
        """
        latest: dict[str, PhaseRecord] = {}
        for phase in self.phases:
            latest[phase.name] = phase
        return [phase for phase in latest.values() if phase.state in {"intended", "failed"}]


def load_journal(path: Path, installation_id: str) -> InstallJournal:
    """Read the journal, or start a fresh one. A journal is never the reason setup cannot run."""
    try:
        payload = read_private_file(path)
    except DesktopError as exc:
        if exc.code is DesktopErrorCode.CONFIG_MISSING:
            return InstallJournal(installation_id=installation_id)
        raise
    try:
        document = json.loads(payload.decode("utf-8"))
        journal = InstallJournal.model_validate(document)
    except (UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "The recovery journal could not be read.",
            recovery=(
                "Repair the connection from OpenTranscribe Setup. The journal is kept as it is "
                "so nothing that still needs cleaning up is forgotten."
            ),
        ) from exc
    if journal.schema_version != JOURNAL_SCHEMA_VERSION:
        raise DesktopError(
            DesktopErrorCode.CONFIG_UNSUPPORTED_VERSION,
            f"The recovery journal uses schema version {journal.schema_version}.",
            recovery="Use the OpenTranscribe Setup version that wrote it.",
        )
    return journal


def save_journal(path: Path, journal: InstallJournal) -> None:
    payload = json.dumps(journal.model_dump(mode="json"), indent=2, sort_keys=True).encode("utf-8")
    write_private_file(path, payload)
