"""Derive versioned shared-library dependencies from the binaries the build actually produced.

Copying another project's dependency list would be a guess. This reads the payload's ELF files,
asks the system which package provides each library, and emits a `Depends` field. The result must
still be checked on the oldest supported system before it is trusted.
"""

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

# Bundled libraries travel with the payload and must never appear as system dependencies.
_ELF_MAGIC = b"\x7fELF"
_VERSION = re.compile(r"^(?P<package>[^\s:]+):[^\s]*\s+(?P<version>\S+)")


def elf_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as handle:
            if handle.read(4) == _ELF_MAGIC:
                yield path


def needed_libraries(path: Path) -> set[str]:
    objdump = _tool("objdump")
    listing = _run([objdump, "-p", str(path)]) if objdump else None
    return {
        line.split()[1]
        for line in (listing or "").splitlines()
        if line.strip().startswith("NEEDED")
    }


def resolve(libraries: set[str], bundled: set[str]) -> dict[str, str]:
    """Map each system library to its providing package and installed version."""
    query = _tool("dpkg-query")
    catalogue = _library_catalogue()
    packages: dict[str, str] = {}
    for library in sorted(libraries - bundled):
        location = catalogue.get(library)
        if location is None or query is None:
            continue
        owner = _run([query, "-S", location])
        if owner is None:
            continue
        package = owner.split(":", 1)[0].strip()
        version = _run([query, "-W", "-f=${Version}", package])
        if version:
            packages[package] = version.strip()
    return packages


def _library_catalogue() -> dict[str, str]:
    ldconfig = _tool("ldconfig") or "/sbin/ldconfig"
    listing = _run([ldconfig, "-p"]) or ""
    catalogue: dict[str, str] = {}
    for line in listing.splitlines():
        stripped = line.strip()
        if "=>" not in stripped:
            continue
        catalogue.setdefault(stripped.split()[0], stripped.split("=>", 1)[1].strip())
    return catalogue


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _run(argv: list[str]) -> str | None:
    """Run one build tool with a fixed argument vector. There is no shell anywhere here."""
    try:
        result = subprocess.run(  # noqa: S603 - argv is built from resolved tool paths only
            argv, capture_output=True, text=True, check=False, shell=False
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument(
        "--fallback",
        default="libc6 (>= 2.35), libstdc++6 (>= 12), libgl1, libegl1, libxkbcommon0, "
        "libfontconfig1, libfreetype6, libdbus-1-3",
        help="Used only when the build host cannot be queried; it must then be reviewed by hand.",
    )
    arguments = parser.parse_args()

    if not shutil.which("objdump") or not shutil.which("dpkg-query"):
        sys.stderr.write(
            "objdump or dpkg-query is unavailable; emitting the reviewed fallback list.\n"
        )
        sys.stdout.write(arguments.fallback)
        return 0

    bundled = {path.name for path in arguments.payload.rglob("*.so*")}
    required: set[str] = set()
    for path in elf_files(arguments.payload):
        required |= needed_libraries(path)
    packages = resolve(required, bundled)
    if not packages:
        sys.stderr.write("no system libraries were resolved; emitting the reviewed fallback.\n")
        sys.stdout.write(arguments.fallback)
        return 0
    sys.stdout.write(
        ", ".join(
            f"{name} (>= {version.split('-', 1)[0]})" for name, version in sorted(packages.items())
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
