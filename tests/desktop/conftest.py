import os
from pathlib import Path

import pytest

from open_transcribe.desktop.credentials import InMemoryCredentialStore
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.schema import ManagedConfig


@pytest.fixture
def desktop_paths(tmp_path: Path) -> DesktopPaths:
    """A whole XDG environment under tmp_path, including a private runtime directory."""
    return DesktopPaths.resolve(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        }
    )


@pytest.fixture
def credentials() -> InMemoryCredentialStore:
    return InMemoryCredentialStore()


@pytest.fixture
def engine_stub(tmp_path: Path) -> Path:
    """An executable that runs this checkout's CLI, standing in for the packaged engine."""
    import sys

    path = tmp_path / "open-transcribe-mcp"
    # Absolute entries only: the engine is started from a bare environment and another working
    # directory, exactly as a client would start it.
    import_path = os.pathsep.join(
        str(Path(entry).resolve()) for entry in sys.path if entry and Path(entry).is_dir()
    )
    path.write_text(
        "#!/bin/sh\n"
        f'PYTHONPATH="{import_path}" exec "{sys.executable}" -m open_transcribe.cli "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


@pytest.fixture
def managed_config() -> ManagedConfig:
    return ManagedConfig(schema_version=1, installation_id="0" * 32)


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No desktop test may read the developer's own configuration or keyring."""
    for name in ("OT_GROQ__API_KEY", "OT_SECURITY__BEARER_TOKEN", "OT_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
