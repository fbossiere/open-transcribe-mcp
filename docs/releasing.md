# Release process

Publishing is automated when a GitHub release is published. The release workflow validates and
tests the tagged source, builds the wheel and source distribution once, publishes them to PyPI
with Trusted Publishing, and then publishes `server.json` to the official MCP Registry.

No long-lived publication token is stored in GitHub. Both registries use GitHub OIDC.

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
   uv run python scripts/check_release_metadata.py --tag v0.1.0
   ```

4. Merge the release preparation pull request.
5. Create and publish the matching GitHub release from the tagged `main` commit.

The workflow rejects malformed tags and any mismatch among the tag, Python package version, MCP
server version, and MCP package version. PyPI must succeed before MCP Registry publication begins.
Rerunning a partially successful workflow is safe only for the failed job: registry versions are
immutable and PyPI does not allow uploading an existing filename again.
