"""The per-user cleanup timer for temporary audio.

It is installed only as part of the reviewed temporary-processing opt-in, never from a root
maintainer script. It makes no network call, deletes only verified expired files this
installation owns, and is not a transcription service. If the packaged executable is gone, its
service succeeds and does nothing, so a removed package cannot leave a unit failing in a loop.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.installation import Installation


def _repository_unit(name: str) -> Path:
    """A development checkout serves the units from the packaging directory."""
    return Path(__file__).resolve().parents[3] / "packaging" / "desktop" / name


SERVICE_NAME = "open-transcribe-cleanup.service"
TIMER_NAME = "open-transcribe-cleanup.timer"
_TIMEOUT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class CleanupTimer:
    """The user units this installation owns, and the commands that manage them."""

    unit_dir: Path
    installation: Installation
    systemctl: Path | None = None

    @classmethod
    def for_user(cls, installation: Installation, home: Path | None = None) -> "CleanupTimer":
        base = (home or Path.home()) / ".config" / "systemd" / "user"
        found = shutil.which("systemctl")
        return cls(
            unit_dir=base,
            installation=installation,
            systemctl=Path(found) if found else None,
        )

    @property
    def available(self) -> bool:
        return self.systemctl is not None

    @property
    def installed(self) -> bool:
        return (self.unit_dir / TIMER_NAME).is_file()

    def install(self) -> None:
        """Install and start the timer. Called only after the user approved relay processing."""
        if not self.available:
            raise DesktopError(
                DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE,
                "This session cannot run the cleanup timer, so temporary audio processing "
                "cannot expire reliably and stays unavailable.",
                recovery="Choose a model that can fetch the audio URL itself.",
            )
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        for name in (SERVICE_NAME, TIMER_NAME):
            source = self._packaged_unit(name)
            (self.unit_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        self._systemctl("daemon-reload")
        self._systemctl("enable", "--now", TIMER_NAME)

    def remove(self) -> bool:
        """Remove the units this installation wrote, and nothing else."""
        if not self.installed:
            return True
        removed = True
        if self.available:
            removed = self._systemctl("disable", "--now", TIMER_NAME)
        for name in (TIMER_NAME, SERVICE_NAME):
            (self.unit_dir / name).unlink(missing_ok=True)
        if self.available:
            self._systemctl("daemon-reload")
        return removed

    def _packaged_unit(self, name: str) -> Path:
        for candidate in (
            self.installation.root / "share" / name,
            self.installation.root.parent / "share" / "open-transcribe-assistant" / name,
            _repository_unit(name),
        ):
            if candidate.is_file():
                return candidate
        raise DesktopError(
            DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE,
            "The packaged cleanup units are missing.",
            recovery="Reinstall the OpenTranscribe Setup package.",
        )

    def _systemctl(self, *arguments: str) -> bool:
        assert self.systemctl is not None  # noqa: S101 - guarded by `available`
        try:
            result = subprocess.run(  # noqa: S603 - fixed vector, absolute executable, no shell
                [str(self.systemctl), "--user", *arguments],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0
