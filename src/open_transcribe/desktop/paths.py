"""XDG locations for the managed desktop profile, with ownership and permission checks.

Containment and ownership are decided by real file operations on opened descriptors rather than
by comparing path strings, so a symlinked or relocated managed file fails closed.
"""

import errno
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

APPLICATION_DIRNAME = "open-transcribe-mcp"
PROFILE_DIRNAME = "desktop"
CONFIG_FILENAME = "config.toml"
JOURNAL_FILENAME = "install.json"
LOCK_FILENAME = ".lock"

_PRIVATE_DIR_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


def _base(environ: Mapping[str, str], name: str, fallback: Path) -> Path:
    raw = environ.get(name, "").strip()
    if raw and Path(raw).is_absolute():
        return Path(raw)
    return fallback


@dataclass(frozen=True, slots=True)
class DesktopPaths:
    """Every managed location the desktop profile is allowed to touch."""

    config_dir: Path
    data_dir: Path
    state_dir: Path
    runtime_dir: Path | None

    @classmethod
    def resolve(cls, environ: Mapping[str, str] | None = None) -> "DesktopPaths":
        env = os.environ if environ is None else environ
        home = Path(env.get("HOME") or Path.home())
        suffix = Path(APPLICATION_DIRNAME) / PROFILE_DIRNAME
        runtime_root = env.get("XDG_RUNTIME_DIR", "").strip()
        return cls(
            config_dir=_base(env, "XDG_CONFIG_HOME", home / ".config") / suffix,
            data_dir=_base(env, "XDG_DATA_HOME", home / ".local" / "share") / suffix,
            state_dir=_base(env, "XDG_STATE_HOME", home / ".local" / "state") / suffix,
            runtime_dir=(
                Path(runtime_root) / APPLICATION_DIRNAME
                if runtime_root and Path(runtime_root).is_absolute()
                else None
            ),
        )

    @property
    def config_file(self) -> Path:
        return self.config_dir / CONFIG_FILENAME

    @property
    def journal_file(self) -> Path:
        return self.state_dir / JOURNAL_FILENAME

    @property
    def lock_file(self) -> Path:
        return self.state_dir / LOCK_FILENAME


def ensure_private_dir(path: Path) -> Path:
    """Create or validate a `0700` directory this user owns, refusing symlinked components."""
    path.mkdir(mode=_PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    fd = _open_checked(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid():
            raise DesktopError(
                DesktopErrorCode.CONFIG_UNSAFE_LOCATION,
                f"{path} is not owned by the current user.",
                recovery="Fix the directory ownership, or remove it and open Setup again.",
            )
        if info.st_mode & 0o077:
            os.fchmod(fd, _PRIVATE_DIR_MODE)
    finally:
        os.close(fd)
    return path


def open_private_file(path: Path) -> int:
    """Open an existing managed file for reading, refusing symlinks and shared permissions.

    Every property is checked on the open descriptor, not on the path, so the file that is read
    is the same file that was validated.
    """
    fd = _open_checked(path, os.O_RDONLY)
    problem = _describe_unsafe_file(path, os.fstat(fd))
    if problem is not None:
        os.close(fd)
        raise problem
    return fd


def _describe_unsafe_file(path: Path, info: os.stat_result) -> DesktopError | None:
    if not stat.S_ISREG(info.st_mode):
        return DesktopError(
            DesktopErrorCode.CONFIG_UNSAFE_LOCATION, f"{path} is not a regular file."
        )
    if info.st_uid != os.getuid():
        return DesktopError(
            DesktopErrorCode.CONFIG_UNSAFE_LOCATION,
            f"{path} is not owned by the current user.",
            recovery="Fix the file ownership, or erase the saved setup and configure again.",
        )
    if info.st_mode & 0o077:
        return DesktopError(
            DesktopErrorCode.CONFIG_UNSAFE_LOCATION,
            f"{path} is readable by other users.",
            recovery=f"Run: chmod 600 {path}",
        )
    return None


def _open_checked(path: Path, flags: int) -> int:
    try:
        return os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError as exc:
        raise DesktopError(DesktopErrorCode.CONFIG_MISSING, f"{path} does not exist.") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise DesktopError(
                DesktopErrorCode.CONFIG_UNSAFE_LOCATION,
                f"{path} is a symbolic link; managed files must be real files.",
            ) from exc
        raise DesktopError(
            DesktopErrorCode.CONFIG_UNSAFE_LOCATION, f"{path} could not be opened safely."
        ) from exc


def write_private_file(path: Path, payload: bytes) -> None:
    """Replace a managed file atomically, leaving the previous version readable on failure."""
    ensure_private_dir(path.parent)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _PRIVATE_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def read_private_file(path: Path) -> bytes:
    fd = open_private_file(path)
    with os.fdopen(fd, "rb") as handle:
        return handle.read()
