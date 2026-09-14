"""Refuse a package that carries anything from the build machine.

Run before `dpkg-deb --build`. It fails on a home directory, an environment file, a private key,
a test result, or a source tree that should never reach a user's computer, and it checks that the
package's own required files are present and executable.
"""

import argparse
import os
import re
import stat
import sys
from pathlib import Path

PROHIBITED_NAMES = {
    ".env",
    ".env.local",
    ".git",
    ".pytest_cache",
    ".coverage",
    "id_rsa",
    # Records how a distribution was installed on the build host, including its home directory.
    "direct_url.json",
}
PROHIBITED_SUFFIXES = {".pem", ".key", ".pyc.orig", ".log"}
# The bundled CA store is the one legitimate `.pem`: the package trusts the same roots the
# system does, and providers are reached over HTTPS.
ALLOWED_NAMES = {"cacert.pem"}
PROHIBITED_CONTENT = re.compile(rb"/(home|root)/[A-Za-z0-9._-]+/")
SCANNED_SUFFIXES = {".toml", ".json", ".txt", ".cfg", ".ini", ".desktop", ".xml", ".service"}

REQUIRED = (
    "DEBIAN/control",
    "usr/bin/open-transcribe-assistant",
    "usr/share/applications/open-transcribe-assistant.desktop",
    "usr/share/icons/hicolor/scalable/apps/open-transcribe-assistant.svg",
    "usr/share/metainfo/io.github.fbossiere.OpenTranscribeSetup.metainfo.xml",
    "usr/share/doc/open-transcribe-assistant/LICENSE",
    "usr/share/doc/open-transcribe-assistant/THIRD-PARTY-NOTICES",
    "opt/open-transcribe-assistant/open-transcribe-assistant",
    "opt/open-transcribe-assistant/open-transcribe-mcp",
    # PyInstaller's one-directory layout keeps bundled data under `_internal/`.
    "opt/open-transcribe-assistant/_internal/open_transcribe/config/pricing.yaml",
    "opt/open-transcribe-assistant/_internal/open_transcribe/config/routing.yaml",
    "opt/open-transcribe-assistant/_internal/open_transcribe/config/desktop/clients.toml",
)
EXECUTABLE = (
    "usr/bin/open-transcribe-assistant",
    "opt/open-transcribe-assistant/open-transcribe-assistant",
    "opt/open-transcribe-assistant/open-transcribe-mcp",
)
FORBIDDEN_PATHS = ("usr/bin/open-transcribe-mcp",)


def check(stage: Path) -> list[str]:
    problems: list[str] = []
    for name in REQUIRED:
        if not (stage / name).exists():
            problems.append(f"missing required file: {name}")
    for name in EXECUTABLE:
        path = stage / name
        if path.exists() and not os.access(path, os.X_OK):
            problems.append(f"not executable: {name}")
    for name in FORBIDDEN_PATHS:
        if (stage / name).exists():
            problems.append(f"must not be on PATH: {name}")

    for path in stage.rglob("*"):
        relative = path.relative_to(stage).as_posix()
        if path.name in ALLOWED_NAMES:
            continue
        if path.name in PROHIBITED_NAMES or path.suffix in PROHIBITED_SUFFIXES:
            problems.append(f"build leftover: {relative}")
            continue
        if not path.is_file() or path.is_symlink():
            continue
        info = path.lstat()
        if info.st_mode & stat.S_IWOTH:
            problems.append(f"world-writable: {relative}")
        if path.suffix in SCANNED_SUFFIXES and path.stat().st_size < 512 * 1024:
            match = PROHIBITED_CONTENT.search(path.read_bytes())
            if match:
                problems.append(f"build-machine path in {relative}: {match.group().decode()}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", type=Path)
    problems = check(parser.parse_args().stage)
    for problem in problems:
        sys.stderr.write(f"{problem}\n")
    if problems:
        return 1
    sys.stdout.write("payload inspection passed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
