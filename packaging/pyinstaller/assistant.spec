# PyInstaller specification for OpenTranscribe Setup.
#
# The assistant and the engine are separate executables built from the same source revision in
# the same run, so the version the window reports is the version the client launches.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

ROOT = Path(os.environ.get("OT_SOURCE_ROOT", ".")).resolve()

datas = [
    (str(ROOT / "config" / "pricing.yaml"), "open_transcribe/config"),
    (str(ROOT / "config" / "routing.yaml"), "open_transcribe/config"),
    (str(ROOT / "config" / "desktop" / "clients.toml"), "open_transcribe/config/desktop"),
    (str(ROOT / "packaging" / "desktop" / "open-transcribe-assistant.svg"), "share"),
    (str(ROOT / "LICENSE"), "share"),
]
for distribution in ("fastmcp", "mcp", "mcp-types", "open-transcribe-mcp", "keyring"):
    try:
        datas += copy_metadata(distribution)
    except Exception:  # noqa: BLE001
        pass
datas += collect_data_files("certifi")

hiddenimports = [
    "keyring.backends.SecretService",
    "secretstorage",
    "jeepney",
    "jeepney.io.blocking",
    "tomli_w",
]

analysis = Analysis(
    [str(ROOT / "packaging" / "pyinstaller" / "assistant_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="open-transcribe-assistant",
    console=False,
    strip=False,
    upx=False,
)
COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="assistant",
)
