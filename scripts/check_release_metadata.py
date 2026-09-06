"""Fail a release when its tag and public package metadata disagree."""

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER_NAME = "io.github.fbossiere/open-transcribe-mcp"


def _read_project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project: dict[str, Any] = tomllib.load(handle)
    return str(project["project"]["version"])


def _read_server_metadata() -> dict[str, Any]:
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def validate(tag: str) -> None:
    match = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag)
    if match is None:
        raise ValueError(f"release tag must be a stable SemVer tag such as v0.1.0, got {tag!r}")

    version = tag.removeprefix("v")
    project_version = _read_project_version()
    server = _read_server_metadata()
    package_versions = [str(package.get("version")) for package in server.get("packages", [])]
    expected_marker = f"<!-- mcp-name: {SERVER_NAME} -->"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    errors: list[str] = []
    if project_version != version:
        errors.append(f"pyproject.toml version is {project_version}, expected {version}")
    if server.get("name") != SERVER_NAME:
        errors.append(f"server.json name is {server.get('name')!r}, expected {SERVER_NAME!r}")
    if server.get("version") != version:
        errors.append(f"server.json version is {server.get('version')!r}, expected {version!r}")
    if not package_versions:
        errors.append("server.json must declare at least one package")
    elif any(package_version != version for package_version in package_versions):
        errors.append(
            f"server.json package versions are {package_versions!r}, expected only {version!r}"
        )
    if expected_marker not in readme:
        errors.append(f"README.md is missing MCP Registry ownership marker {expected_marker!r}")
    if f"## [{version}]" not in changelog:
        errors.append(f"CHANGELOG.md is missing a {version} release heading")
    if f"open-transcribe-mcp:{version}" not in readme:
        errors.append(f"README.md has no Docker example for version {version}")

    if errors:
        raise ValueError("release metadata validation failed:\n- " + "\n- ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="GitHub release tag, for example v0.1.0")
    args = parser.parse_args()
    validate(args.tag)


if __name__ == "__main__":
    main()
