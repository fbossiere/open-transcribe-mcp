"""Inspect built distributions for required and prohibited release content."""

import email
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PROHIBITED_SUFFIXES = {".env", ".key", ".pem", ".mp3", ".wav", ".m4a"}


def _one(pattern: str) -> Path:
    matches = sorted(DIST.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {pattern} artifact, found {matches}")
    return matches[0]


def _reject_prohibited(names: list[str]) -> None:
    prohibited = [
        name
        for name in names
        if Path(name).suffix.lower() in PROHIBITED_SUFFIXES or Path(name).name == ".env"
    ]
    if prohibited:
        raise ValueError(f"distribution contains prohibited files: {prohibited}")


def _require(names: list[str], suffixes: tuple[str, ...]) -> None:
    missing = [suffix for suffix in suffixes if not any(name.endswith(suffix) for name in names)]
    if missing:
        raise ValueError(f"distribution is missing required files: {missing}")


def inspect_wheel(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        _reject_prohibited(names)
        _require(
            names,
            (
                "open_transcribe/__init__.py",
                "open_transcribe/py.typed",
                "open_transcribe/config/pricing.yaml",
                "open_transcribe/config/routing.yaml",
                ".dist-info/licenses/LICENSE",
                ".dist-info/METADATA",
            ),
        )
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_name))
    if metadata.get("Name") != "open-transcribe-mcp":
        raise ValueError("wheel metadata contains the wrong project name")
    if metadata.get("License-Expression") != "Apache-2.0":
        raise ValueError("wheel metadata is missing the Apache-2.0 license expression")
    return str(metadata["Version"])


def inspect_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
    _reject_prohibited(names)
    _require(
        names,
        (
            "/LICENSE",
            "/README.md",
            "/pyproject.toml",
            "/src/open_transcribe/py.typed",
        ),
    )


def main() -> None:
    wheel = _one("*.whl")
    sdist = _one("*.tar.gz")
    version = inspect_wheel(wheel)
    inspect_sdist(sdist)
    sys.stdout.write(f"Validated wheel and sdist for open-transcribe-mcp {version}.\n")


if __name__ == "__main__":
    main()
