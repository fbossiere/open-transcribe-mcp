# Release process

Publishing is automated when a stable version tag from `main` is pushed. The release workflow
validates and tests the tagged source, builds and inspects the Python distributions, publishes them
to PyPI with Trusted Publishing, publishes `server.json` to the official MCP Registry, and pushes
a provenance-attested image to GHCR. It creates the immutable GitHub release with checksums and a
CycloneDX container SBOM only after every publication succeeds.

No long-lived publication token is stored in GitHub. PyPI and the MCP Registry use GitHub OIDC;
GHCR uses the release job's short-lived, package-scoped `GITHUB_TOKEN`, and provenance attestation
uses OIDC.

## One-time PyPI setup

Before the first release, register a pending Trusted Publisher in the PyPI account that will own
`open-transcribe-mcp`:

| Field | Value |
| --- | --- |
| PyPI project name | `open-transcribe-mcp` |
| GitHub owner | `fbossiere` |
| GitHub repository | `open-transcribe-mcp` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Create a protected GitHub environment named `pypi`. Restrict deployment branches and tags to
protected tags matching `v*`; optionally require a maintainer approval for production publishing.
The first successful workflow run creates the PyPI project and converts the pending publisher to
a normal Trusted Publisher.

The MCP Registry needs no repository secret. Its GitHub OIDC login verifies the
`io.github.fbossiere/open-transcribe-mcp` namespace. PyPI ownership is verified through the
matching `mcp-name` marker in `README.md`.

## Publish a release

1. Update the version in `pyproject.toml`, `server.json`, and every package entry in `server.json`.
2. Move the relevant changelog entries from `Unreleased` into a dated version section.
3. Run the full validation suite and validate the release metadata:

   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy
   uv run pytest --cov
   uv run mkdocs build --strict
   uv run pip-audit
   uv build
   uv run python scripts/check_distribution.py
   uv run python scripts/check_release_metadata.py --tag v1.0.0
   ```

4. Merge the release preparation pull request.
5. Create and push the matching tag from the merged `main` commit.
6. Wait for the release workflow to publish and verify PyPI, MCP Registry, GHCR, and the GitHub release.

The workflow rejects malformed tags, tags not reachable from `main`, and mismatches among the tag,
changelog, README example, Python package version, MCP server version, and MCP package version.
PyPI must succeed before MCP Registry publication begins. Rerunning a partially successful workflow
is safe only for a failed job: registry versions are immutable and PyPI does not allow uploading an
existing filename again.
