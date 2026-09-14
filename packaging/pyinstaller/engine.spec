# PyInstaller specification for the headless transcription engine.
#
# One-directory bundle: its libraries and data are inspectable in the installed tree, and it does
# not extract executable dependencies to a temporary directory on every launch.
#
# No Qt, and no interface module, reaches this bundle. Keeping the engine importable without a
# display is a release requirement, not an optimisation.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

ROOT = Path(os.environ.get("OT_SOURCE_ROOT", ".")).resolve()

datas = [
    (str(ROOT / "config" / "pricing.yaml"), "open_transcribe/config"),
    (str(ROOT / "config" / "routing.yaml"), "open_transcribe/config"),
    (str(ROOT / "config" / "desktop" / "clients.toml"), "open_transcribe/config/desktop"),
]
# FastMCP and the MCP SDK read their own distribution metadata at runtime; a successful import on
# the build host does not put that metadata in the bundle.
for distribution in ("fastmcp", "mcp", "mcp-types", "open-transcribe-mcp", "keyring"):
    try:
        datas += copy_metadata(distribution)
    except Exception:  # noqa: BLE001 - a missing optional distribution is reported by the checker
        pass
datas += collect_data_files("certifi")

hiddenimports = [
    # Keyring resolves its backends by entry point, so they must be named explicitly.
    "keyring.backends.SecretService",
    "keyring.backends.chainer",
    "keyring.backends.fail",
    "secretstorage",
    "jeepney",
    "jeepney.io.blocking",
    "open_transcribe.providers.microsoft.adapter",
    "open_transcribe.providers.elevenlabs.adapter",
    "open_transcribe.providers.groq.adapter",
]

analysis = Analysis(
    [str(ROOT / "packaging" / "pyinstaller" / "engine_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6", "shiboken6", "tkinter", "open_transcribe.desktop.gui"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="open-transcribe-mcp",
    console=True,
    strip=False,
    upx=False,
)
COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="engine",
)
