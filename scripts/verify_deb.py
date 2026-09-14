"""Inspect a built `.deb` and run its extracted engine in an isolated environment.

This is the PKG-04 check: the archive is opened, its contents and metadata are verified, and the
engine inside it is started with no system Python, no project checkout, and no user `PATH`. A
successful build on the build host is not evidence that the package works.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PREFIX = "opt/open-transcribe-assistant"
REQUIRED_CONTROL_FIELDS = (
    "Package",
    "Version",
    "Architecture",
    "Maintainer",
    "Homepage",
    "Installed-Size",
    "Depends",
    "Description",
)


def _run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed vectors built from resolved tool paths
        argv, capture_output=True, text=True, check=False, shell=False, **kwargs
    )


def inspect_control(archive: Path) -> dict[str, str]:
    dpkg_deb = shutil.which("dpkg-deb")
    if dpkg_deb is None:
        raise SystemExit("dpkg-deb is required to inspect the package")
    result = _run([dpkg_deb, "--field", str(archive)])
    if result.returncode != 0:
        raise SystemExit(f"could not read the package control fields: {result.stderr.strip()}")
    fields = {}
    for line in result.stdout.splitlines():
        if line and not line.startswith(" ") and ":" in line:
            name, value = line.split(":", 1)
            fields[name.strip()] = value.strip()
    missing = [name for name in REQUIRED_CONTROL_FIELDS if not fields.get(name)]
    if missing:
        raise SystemExit(f"the package control file is missing: {missing}")
    if fields["Architecture"] != "amd64":
        raise SystemExit(f"unexpected architecture: {fields['Architecture']}")
    return fields


def extract(archive: Path, target: Path) -> None:
    dpkg_deb = shutil.which("dpkg-deb")
    assert dpkg_deb is not None  # noqa: S101 - checked by the caller
    result = _run([dpkg_deb, "--extract", str(archive), str(target)])
    if result.returncode != 0:
        raise SystemExit(f"could not extract the package: {result.stderr.strip()}")


def check_engine(root: Path, expected_version: str) -> None:
    """Start the extracted engine with nothing from this machine on its path."""
    engine = root / PREFIX / "open-transcribe-mcp"
    if not engine.is_file() or not os.access(engine, os.X_OK):
        raise SystemExit("the extracted package has no executable engine")

    isolated = Path(tempfile.mkdtemp(prefix="open-transcribe-verify-"))
    config = isolated / "config.toml"
    config.write_text(
        'schema_version = 1\ninstallation_id = "' + "0" * 32 + '"\n', encoding="utf-8"
    )
    config.chmod(0o600)
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(isolated)}
    result = _run(
        [str(engine), "doctor", "--config", str(config), "--json"],
        cwd="/",
        env=environment,
        timeout=120,
    )
    if result.returncode not in {0, 1}:
        raise SystemExit(f"the extracted engine failed to run: {result.stderr[-2000:]}")
    try:
        report = json.loads(result.stdout)
    except ValueError as exc:
        preview = result.stdout[:400]
        raise SystemExit(f"the engine produced no diagnostic report: {preview}") from exc
    if report.get("schema") != "open-transcribe-diagnostic/1":
        raise SystemExit("the engine produced an unexpected diagnostic schema")
    if report.get("application_version") != expected_version:
        raise SystemExit(
            f"engine version {report.get('application_version')!r} does not match the package "
            f"version {expected_version!r}"
        )
    shutil.rmtree(isolated, ignore_errors=True)


def check_payload(root: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_deb_payload import check  # type: ignore[import-not-found]

    problems = check(root)
    # The extracted tree has no DEBIAN directory; that one absence is expected here.
    problems = [item for item in problems if "DEBIAN/control" not in item]
    if problems:
        for problem in problems:
            sys.stderr.write(f"{problem}\n")
        raise SystemExit("the extracted package failed inspection")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    archive = parser.parse_args().archive
    if not archive.is_file():
        raise SystemExit(f"no such package: {archive}")

    fields = inspect_control(archive)
    upstream_version = fields["Version"].split("-", 1)[0]
    with tempfile.TemporaryDirectory(prefix="open-transcribe-deb-") as workspace:
        root = Path(workspace)
        extract(archive, root)
        check_payload(root)
        check_engine(root, upstream_version)
    sys.stdout.write(f"{archive.name}: control, payload, and isolated engine launch all verified\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
