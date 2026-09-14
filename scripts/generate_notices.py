"""Collect third-party licence notices for the components this build actually bundles.

This produces the notice file shipped in the package. It is an input to the licence review, not
a substitute for it: source and relinking obligations for bundled native components must be
confirmed by a human before a release.
"""

import argparse
import sys
from importlib import metadata
from pathlib import Path

HEADER = """OpenTranscribe Setup — third-party notices
=========================================

This package bundles a Python runtime, Qt components, and the Python distributions listed below.
Each keeps its own licence. Where a bundled component's licence carries source-availability or
relinking obligations, those are honoured through the release's published SBOM and source
archive; see https://github.com/fbossiere/open-transcribe-mcp/releases.

"""


def collect() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if not name:
            continue
        licence = (
            distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or _classifier_licence(distribution)
            or "see distribution metadata"
        )
        rows.append((name, distribution.version or "unknown", licence.splitlines()[0][:120]))
    return sorted(set(rows))


def _classifier_licence(distribution: metadata.Distribution) -> str | None:
    for classifier in distribution.metadata.get_all("Classifier") or []:
        if classifier.startswith("License :: "):
            return classifier.rsplit("::", 1)[-1].strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    rows = collect()
    if not rows:
        sys.stderr.write("no distributions were found; refusing to write an empty notice file\n")
        return 1
    lines = [HEADER]
    width = max(len(name) for name, _, _ in rows)
    for name, version, licence in rows:
        lines.append(f"{name.ljust(width)}  {version:<16}  {licence}")
    lines.append("")
    lines.append(
        "The Qt components are used under the LGPL v3. The bundle links them dynamically and the "
        "release publishes the corresponding sources and the object files needed to relink."
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {arguments.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
