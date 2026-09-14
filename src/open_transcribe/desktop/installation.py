"""Where the packaged application lives, and which engine a client must be pointed at.

Managed registrations always name the packaged engine by absolute path. They never rely on
`PATH`, never point at a Python interpreter, and never shadow a CLI installation in the user's
home directory.
"""

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

PACKAGE_ROOT = Path("/opt/open-transcribe-assistant")
ENGINE_NAME = "open-transcribe-mcp"
ASSISTANT_NAME = "open-transcribe-assistant"
DEVELOPMENT_ROOT_ENV = "OT_DESKTOP_PACKAGE_ROOT"
"""A development override. It is read only when the packaged layout is absent."""


@dataclass(frozen=True, slots=True)
class Installation:
    root: Path
    engine: Path
    assistant: Path
    config_dir: Path
    packaged: bool

    @property
    def version(self) -> str:
        from open_transcribe import __version__

        return __version__


@lru_cache(maxsize=1)
def current_installation() -> Installation:
    root = _root()
    engine = root / ENGINE_NAME
    config_dir = root / "config" if (root / "config").is_dir() else _repository_config()
    return Installation(
        root=root,
        engine=engine,
        assistant=root / ASSISTANT_NAME,
        config_dir=config_dir,
        packaged=engine.is_file(),
    )


def engine_executable() -> Path:
    """The exact executable a client is registered to launch."""
    installation = current_installation()
    if installation.packaged and os.access(installation.engine, os.X_OK):
        return installation.engine
    raise DesktopError(
        DesktopErrorCode.ENGINE_MISSING,
        "The packaged transcription engine was not found next to this application.",
        recovery="Reinstall the OpenTranscribe Setup package.",
    )


def _root() -> Path:
    if (PACKAGE_ROOT / ENGINE_NAME).is_file():
        return PACKAGE_ROOT
    override = os.environ.get(DEVELOPMENT_ROOT_ENV, "").strip()
    if override and Path(override).is_absolute():
        return Path(override)
    if getattr(sys, "frozen", False):  # pragma: no cover - only inside a bundle
        return Path(sys.executable).resolve().parent
    return PACKAGE_ROOT


def _repository_config() -> Path:
    from open_transcribe.settings import _default_config_dir

    return _default_config_dir()
