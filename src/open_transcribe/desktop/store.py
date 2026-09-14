"""Reading and writing the managed configuration, and the per-installation lock.

A write is atomic and leaves the previous readable version in place if it is interrupted. A read
fails closed on an unsafe location, an unknown schema version, or a malformed document.
"""

import fcntl
import os
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.paths import (
    DesktopPaths,
    ensure_private_dir,
    read_private_file,
    write_private_file,
)
from open_transcribe.desktop.schema import SCHEMA_VERSION, ManagedConfig

_MAX_CONFIG_BYTES = 256 * 1024


def load_managed_config(path: Path) -> ManagedConfig:
    """Load and validate the managed configuration at an explicit absolute path."""
    if not path.is_absolute():
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "The managed configuration path must be absolute.",
        )
    payload = read_private_file(path)
    if len(payload) > _MAX_CONFIG_BYTES:
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "The managed configuration is larger than this build accepts.",
        )
    try:
        document: dict[str, Any] = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "The managed configuration is not readable TOML.",
            recovery="Open OpenTranscribe Setup to rebuild the configuration.",
        ) from exc
    _require_known_version(document)
    try:
        return ManagedConfig.model_validate(document)
    except ValidationError as exc:
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "The managed configuration does not match this build's schema.",
            recovery="Open OpenTranscribe Setup to review and repair the saved setup.",
        ) from exc


def _require_known_version(document: dict[str, Any]) -> None:
    """Separate "written by a newer build" from "corrupt", so a downgrade never mutates."""
    version = document.get("schema_version")
    if version == SCHEMA_VERSION:
        return
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise DesktopError(
            DesktopErrorCode.CONFIG_UNSUPPORTED_VERSION,
            f"The saved setup uses schema version {version}; this build reads {SCHEMA_VERSION}.",
            recovery=(
                "Install the newer OpenTranscribe Setup again, or erase the saved setup from a "
                "build that understands it. This build will not modify it."
            ),
        )
    raise DesktopError(
        DesktopErrorCode.CONFIG_INVALID,
        "The managed configuration does not declare a schema version this build reads.",
        recovery="Open OpenTranscribe Setup to rebuild the configuration.",
    )


def save_managed_config(path: Path, config: ManagedConfig) -> None:
    """Replace the managed configuration atomically with a coherent, validated document.

    Writing is a Setup operation, so the TOML writer is imported here rather than at module
    scope: the engine only ever reads, and reads with the standard library.
    """
    import tomli_w

    payload = tomli_w.dumps(config.to_toml_dict()).encode("utf-8")
    write_private_file(path, payload)


@contextmanager
def installation_lock(paths: DesktopPaths, *, blocking: bool = False) -> Iterator[None]:
    """Serialize writers for one installation. Discovery and reads do not take this lock."""
    ensure_private_dir(paths.state_dir)
    fd = os.open(paths.lock_file, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DesktopError(
                DesktopErrorCode.CONFIG_LOCKED,
                "Another OpenTranscribe Setup operation is in progress.",
                recovery="Wait for it to finish, or close the other Setup window.",
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
