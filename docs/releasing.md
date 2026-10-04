# Publication protocol

This is the maintainer runbook for a public release. The current stable version is **1.2.1**.
Publishing artifacts and updating a Scaleway deployment are separate operations: the release
workflow has no Scaleway deployment credentials. For runtime updates, follow the
[Scaleway guide](deploy-scaleway.md#upgrades-configuration-changes-and-rollback).

## Choose a version

Use stable semantic versions: `MAJOR.MINOR.PATCH`. Increment the major version for incompatible
public contracts, the minor version for compatible features, and the patch version for compatible
fixes. Describe consequential privacy/configuration changes explicitly in the changelog, even
when they do not change a tool schema. Documentation-only changes can merge and update the site
without creating a release.

| Surface | Example | Meaning |
| --- | --- | --- |
| Git tag / GitHub release | `v1.2.1` | Reviewed source revision; protected against replacement |
| Python package / MCP metadata | `1.2.1` | Immutable registry version |
| OCI image tag | `1.2.1` | Release image; verify its digest before deployment |
| OCI image digest | `sha256:…` | Exact image/index content recorded in `container-digest.txt` |
| GHCR aliases | `1`, `latest` | Moving convenience tags; avoid them for production pins |

A release tag is not an arbitrary deployment name. Never move or delete an already published
version to correct it. Use a new patch release when the tagged application source must change.

## One-time publisher setup

The repository uses `.github/workflows/release.yml`. Register a PyPI Trusted Publisher for
`open-transcribe-mcp` with these values:

| Field | Value |
| --- | --- |
| GitHub owner | `fbossiere` |
| GitHub repository | `open-transcribe-mcp` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Create a protected GitHub environment named `pypi`, restricted to protected tags matching `v*`.
An optional required reviewer can gate publication. A pending publisher becomes a normal
publisher after the first successful upload.

Keep the `main` pull-request checks, `v*` tag protections and immutable GitHub releases enabled.
GHCR packages must permit anonymous pulls; the workflow checks this before completing a release.
For the documentation site, configure **Settings → Pages → Source: GitHub Actions** once.

No long-lived publication token belongs in repository secrets. PyPI and MCP Registry use GitHub
OIDC. GHCR uses the job's short-lived `GITHUB_TOKEN`. The MCP namespace is
`io.github.fbossiere/open-transcribe-mcp`; its ownership marker in `README.md` must remain intact.
Signing keys used by a maintainer for Git commits/tags are separate from publication credentials.

## 1. Prepare the release pull request

Start from current `main`, on a focused branch, with a clean tree. Update all version surfaces:

- `pyproject.toml` and `src/open_transcribe/__init__.py`;
- the root package version in `uv.lock`, refreshed with `uv lock`;
- `server.json`, including every package entry;
- the dated `CHANGELOG.md` section, moving relevant items out of `Unreleased`;
- versioned image examples in `README.md`, the configuration and deployment guides,
  `infra/scaleway/terraform.tfvars.example` and the Terraform `image_tag` default;
- validation examples in this guide and the supported major version in `SECURITY.md` when needed.

Keep personal `terraform.tfvars`, state, keys and deployment endpoints out of the PR. Review
[desktop acceptance](desktop-acceptance.md) and keep unsupported platforms and untested client
registration scenarios explicit. A successful package build is not an end-to-end desktop test.

Install the locked test dependencies and run the complete validation from the repository root:

```bash
uv sync --locked --extra dev --extra s3 --extra desktop
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
uv run mkdocs build --strict
uv run pip-audit
uv build
uv run python scripts/check_distribution.py
uv run python scripts/check_release_metadata.py --tag v1.2.1
```

Replace `v1.2.1` with the intended new version when preparing the next release. The metadata
checker rejects mismatches between the tag, runtime/package versions, registry metadata,
changelog, supported major and public examples. Keep `dist/` limited to the wheel and source
archive for the version being checked. Headless desktop tests need the Qt runtime libraries
installed by CI; see [contributing](https://github.com/fbossiere/open-transcribe-mcp/blob/main/CONTRIBUTING.md) for the development environment.

Sign off commits under the DCO and use the configured signing identity. Open a normal release PR,
attach the validation evidence, wait for all required checks, then merge through the protected
branch rules. Do not create the release tag from an unreviewed feature branch.

## 2. Tag the merged source

Fetch the merged `main`, confirm the release commit and rerun the metadata check there. If the
Git remote is named differently, substitute it for `origin`:

```bash
git fetch origin main --tags
git switch main
git pull --ff-only origin main
git status --short
uv run python scripts/check_release_metadata.py --tag v1.2.1
git tag --sign v1.2.1 --message "OpenTranscribe MCP v1.2.1"
git verify-tag v1.2.1
git push origin v1.2.1
```

These commands illustrate creation of a **new** version. The current `v1.2.1` already exists;
do not recreate it. Stop if the tree is dirty, the tag exists, or the intended release commit is
not the reviewed source. Record the tag's resolved commit, not just its name.

## 3. Follow automated publication

The workflow uses the tagged source and verifies that its commit is reachable from `main`.
Its publication sequence is:

1. Validate metadata, formatting, types, tests and strict documentation; build and inspect the
   Python distributions; smoke-test an installed wheel in a clean environment.
2. Publish Python distributions to PyPI, then publish and verify the MCP Registry version.
3. In parallel after validation, build the Linux desktop package on Ubuntu 24.04 and verify it
   in isolation; build the `linux/amd64` image and publish it to public GHCR.
4. Produce container and desktop CycloneDX SBOMs, provenance inputs and build attestations.
5. Once all publication jobs succeed, create and verify the immutable GitHub release.

The release has eight assets: wheel, source archive, `container-digest.txt`, container SBOM,
Ubuntu amd64 `.deb`, desktop SBOM, desktop provenance JSON and `SHA256SUMS`.
The desktop `.deb.sha256` is a workflow artifact; the release-wide checksum file covers the
uploaded package. This pipeline does not publish macOS/Windows packages or ARM images.

Find the run with `gh run list --workflow release.yml`, then follow its jobs with
`gh run watch RUN_ID --exit-status`. Do not declare success merely because the tag exists or
one registry accepted an upload.

## 4. Verify the public result

Check the exact version in all four publication destinations:

- [GitHub releases](https://github.com/fbossiere/open-transcribe-mcp/releases): public,
  not draft/prerelease, immutable, eight assets and the intended tag commit;
- [PyPI](https://pypi.org/project/open-transcribe-mcp/): wheel and source archive for the version;
- [MCP Registry](https://registry.modelcontextprotocol.io/): the exact server name and version;
- GHCR: anonymous access and the digest in `container-digest.txt`.

For the current stable release, download its assets into an empty temporary directory:

```bash
RELEASE_ASSETS="$(mktemp -d)"
gh release download v1.2.1 --repo fbossiere/open-transcribe-mcp --dir "$RELEASE_ASSETS"
cd "$RELEASE_ASSETS"
sha256sum --check SHA256SUMS
docker buildx imagetools inspect "$(cat container-digest.txt)"
gh attestation verify open-transcribe-assistant_1.2.1-1_amd64.deb --repo fbossiere/open-transcribe-mcp
```

Also compare the Python files' SHA-256 hashes with the exact-version PyPI JSON endpoint and
check that desktop provenance resolves to the tag's source revision. Install the public wheel
in a clean environment outside the checkout and probe `/healthz` with production authentication
configured. Verify documentation navigation after its separate Pages deployment from `main`.

Keep the published digest and the deployment's prior configuration for upgrades/rollback.
No provider key or Scaleway key is needed to download and inspect public artifacts.

## Recovery after partial publication

Inspect which jobs and registries actually succeeded before choosing a recovery action.
PyPI filenames and MCP Registry versions cannot be replaced by republishing the same version.

| Failure state | Recovery |
| --- | --- |
| Validation fails before publication | Fix the source in a new reviewed patch version; leave the protected failed tag in place |
| Transient failure in a job | Rerun only failed jobs: `gh run rerun RUN_ID --failed` |
| PyPI succeeded; MCP publication failed | Retry the failed MCP job after fixing its publication prerequisite; do not rerun the successful PyPI upload |
| PyPI and MCP succeeded; container/desktop jobs failed | Use the repair path below if the tagged source itself needs no change |
| Tagged source is defective | Publish a new patch; explain the superseded version in the changelog |
| Immutable GitHub release already completed | Publish a new patch for artifact changes; do not overwrite assets or tags |

### Repair an already published registry version

When **both** PyPI and MCP Registry publication succeeded, but a later artifact job failed, a
workflow-only fix can merge into `main`. Dispatch that corrected workflow against the existing tag:

```bash
gh workflow run release.yml --repo fbossiere/open-transcribe-mcp --ref main -f tag=v1.2.1
```

The repair rebuilds the immutable tagged source, requires its wheel/source hashes to match PyPI
exactly and verifies the MCP Registry version exists. It skips both immutable registry publishers,
then rebuilds container/desktop artifacts and creates the missing GitHub release. It cannot
recover a version missing from either registry or repair an already completed immutable release.
If source changes are required, use a new version instead.

A repair can change the OCI digest even for the same source tag. Use the digest in the **completed**
release assets, rather than an earlier failed run's build output, when copying to Scaleway.
Review the resulting deployment plan and verify it after applying.
