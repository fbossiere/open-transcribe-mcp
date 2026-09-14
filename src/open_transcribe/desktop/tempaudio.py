"""The owned, expiring runtime area used when temporary audio processing is permitted.

This is the mechanism behind the managed relay permission. It is not a cache and not a history:
it records who owns a file and when it expires, and nothing about where the audio came from.
"""

import contextlib
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.paths import ensure_private_dir

AUDIO_SUFFIX = ".audio"
META_SUFFIX = ".meta"
SWEEP_INTERVAL_SECONDS = 300
"""At least every five minutes while the session is active, per the desktop retention policy."""

MAX_TTL_SECONDS = 3600
_FILE_MODE = 0o600


@dataclass(frozen=True, slots=True)
class SweepReport:
    removed: int = 0
    retained: int = 0
    failed: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        return not self.failed


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:  # pragma: no cover - non-Linux or restricted /proc
        return "unknown"


def _process_start_ticks(pid: int) -> int | None:
    """Distinguish a live owner from an unrelated process that reused its PID."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # The comm field may contain spaces and parentheses; everything after the last ')' is fixed.
    tail = raw.rsplit(")", 1)[-1].split()
    try:
        return int(tail[19])
    except (IndexError, ValueError):  # pragma: no cover - unexpected /proc format
        return None


@dataclass(frozen=True, slots=True)
class TemporaryAudioArea:
    """A per-user directory of short-lived relayed audio files owned by this installation."""

    root: Path
    ttl_seconds: int = MAX_TTL_SECONDS
    max_total_bytes: int = 4 * 1024 * 1024 * 1024
    max_file_bytes: int = 500 * 1024 * 1024

    @classmethod
    def for_runtime_dir(
        cls, runtime_dir: Path | None, *, ttl_seconds: int = MAX_TTL_SECONDS
    ) -> "TemporaryAudioArea":
        if runtime_dir is None:
            raise DesktopError(
                DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE,
                "This session provides no private runtime directory, so temporary audio "
                "processing cannot expire reliably and stays unavailable.",
                recovery="Sign in to a normal user session, or choose a URL-capable model.",
            )
        return cls(root=runtime_dir / "audio", ttl_seconds=min(ttl_seconds, MAX_TTL_SECONDS))

    def prepare(self) -> None:
        ensure_private_dir(self.root)

    def create_file(self) -> str:
        """Create one exclusive, private, unpredictably named file and claim ownership of it."""
        self.prepare()
        self.sweep()
        self._enforce_aggregate_bound()
        token = secrets.token_hex(16)
        target = self.root / f"{token}{AUDIO_SUFFIX}"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _FILE_MODE)
        os.close(fd)
        self._write_claim(token)
        return str(target)

    def release(self, path: str | os.PathLike[str]) -> None:
        """Delete a file and its claim on completion, ordinary failure, or cancellation."""
        target = Path(path)
        if target.parent != self.root or not target.name.endswith(AUDIO_SUFFIX):
            return
        token = target.name[: -len(AUDIO_SUFFIX)]
        target.unlink(missing_ok=True)
        (self.root / f"{token}{META_SUFFIX}").unlink(missing_ok=True)

    def sweep(self, *, expire_all: bool = False) -> SweepReport:
        """Remove expired files and files abandoned by a dead owner, and nothing else.

        Safe to run from several engine processes at once: every removal is best effort, and a
        file another live process still owns and has not let expire is never touched.
        """
        if not self.root.is_dir():
            return SweepReport()
        removed = 0
        retained = 0
        failed: list[str] = []
        now = time.time()
        boot = _boot_id()
        for entry in sorted(self.root.iterdir()):
            if not entry.name.endswith(AUDIO_SUFFIX):
                continue
            token = entry.name[: -len(AUDIO_SUFFIX)]
            meta_path = self.root / f"{token}{META_SUFFIX}"
            if expire_all or self._is_reclaimable(entry, meta_path, now=now, boot=boot):
                try:
                    entry.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                except OSError:
                    failed.append(token)
                else:
                    removed += 1
            else:
                retained += 1
        for entry in sorted(self.root.glob(f"*{META_SUFFIX}")):
            audio = self.root / f"{entry.name[: -len(META_SUFFIX)]}{AUDIO_SUFFIX}"
            if not audio.exists():
                with contextlib.suppress(OSError):
                    entry.unlink(missing_ok=True)
        return SweepReport(removed=removed, retained=retained, failed=tuple(failed))

    def purge(self) -> SweepReport:
        """Clear approved temporary data before disconnection or removal."""
        return self.sweep(expire_all=True)

    def total_bytes(self) -> int:
        if not self.root.is_dir():
            return 0
        total = 0
        for entry in self.root.glob(f"*{AUDIO_SUFFIX}"):
            with contextlib.suppress(OSError):
                info = entry.lstat()
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
        return total

    def _enforce_aggregate_bound(self) -> None:
        if self.total_bytes() >= self.max_total_bytes:
            raise DesktopError(
                DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE,
                "Temporary audio processing has reached its size limit for this session.",
                recovery="Wait for the current transcriptions to finish, then try again.",
            )

    def _write_claim(self, token: str) -> None:
        now = time.time()
        pid = os.getpid()
        claim = {
            "pid": pid,
            "pid_start_ticks": _process_start_ticks(pid),
            "boot_id": _boot_id(),
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
        }
        path = self.root / f"{token}{META_SUFFIX}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(claim, handle)

    def _is_reclaimable(self, audio: Path, meta: Path, *, now: float, boot: str) -> bool:
        try:
            info = audio.lstat()
        except OSError:
            return False
        if not stat.S_ISREG(info.st_mode):
            # Never follow or delete through something that is not a regular file.
            return False
        try:
            claim = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # An audio file without a readable claim is abandoned by definition.
            return now - info.st_mtime > self.ttl_seconds or not meta.exists()
        if not isinstance(claim, dict):
            return True
        if claim.get("boot_id") != boot:
            return True
        expires_at = claim.get("expires_at")
        if not isinstance(expires_at, int | float) or now >= expires_at:
            return True
        return not self._owner_alive(claim)

    @staticmethod
    def _owner_alive(claim: dict[str, object]) -> bool:
        pid = claim.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        current = _process_start_ticks(pid)
        if current is None:
            return False
        expected = claim.get("pid_start_ticks")
        return expected is None or expected == current
