# Contributing

Thank you for improving OpenTranscribe. Provider adapters, security hardening, compatibility fixes, deployment recipes, benchmarks, and documentation are especially welcome.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md), [governance model](GOVERNANCE.md), and [security policy](SECURITY.md) before contributing. For substantial work, open a feature issue first so scope and compatibility can be agreed before implementation begins.

## Development setup

```bash
git clone https://github.com/fbossiere/open-transcribe-mcp.git
cd open-transcribe-mcp
uv sync --extra dev --extra s3
uv run pytest --cov=open_transcribe
uv run ruff format --check .
uv run ruff check .
uv run mypy src
```

`tests/e2e` holds an opt-in suite that transcribes an audio file through a deployed instance; it skips unless `--deployment-url` or `OT_E2E_DEPLOYMENT_URL` is given, and [`docs/deploy-scaleway.md`](docs/deploy-scaleway.md) documents its options.

Python 3.12 is required. Never commit `.env`, provider credentials, signed URLs, personal recordings, or real transcript content.

### Test Groq locally with real credentials

Keep `OT_GROQ__API_KEY` in the git-ignored `.env.local` file, then run:

```bash
uv sync --locked --extra dev --extra s3
uv run pytest tests/integration --live-groq --live-env-file .env.local -q
```

These six checks cover local health and authentication, model capabilities, rejection of
unsupported diarization without a network call, and one real Groq transcription shared by the
remaining checks. They download and upload only the project's short synthetic audio fixture,
verify the canonical result, English reference words, and segment timestamps, and retain no
transcript. The provider call uses `whisper-large-v3-turbo`; select `--groq-model whisper-large-v3`
to test the other Groq model. Normal provider charges and transient-error retries apply.

The suite starts MCP in-process, so no deployed server or listening port is needed. It reads
the specified settings file explicitly and ignores blank entries; it leaves that file unchanged.
The ordinary server command still reads `.env`, not `.env.local`. Test authentication uses an
ephemeral token, storage is disabled, and HTTPS/private-network protections remain enabled.
Without `--live-groq`, these tests skip before reading credentials or making network calls,
including when `.env.local` exists. The English check does not assert bilingual accuracy, since
Groq does not advertise code-switching support.

### Dev container

A [dev container](.devcontainer/devcontainer.json) reproduces the CI toolchain: pinned `uv`, Python 3.12, Docker, Terraform, TFLint, Terragrunt, the GitHub CLI, and the `ffmpeg`/`espeak-ng` pair that `scripts/generate_test_fixture.sh` needs. Open the repository in a supporting editor and reopen in the container, or run `devcontainer up --workspace-folder .`.

The container creates its virtual environment at `/home/vscode/.venv` rather than `./.venv`, so a host environment in the working tree is never reused, and locked dependencies are synced on create. No `.env` is generated: settings load `.env` from the working directory, so copy `.env.example` yourself when you need to run the server. Trivy is not preinstalled — run `scripts/install-trivy.sh ~/.local/bin` when you need the security job locally. TFLint and Terragrunt exceed the CI Terraform job, which runs `fmt`, `init -backend=false`, and `validate` only; [`docs/deploy-scaleway.md`](docs/deploy-scaleway.md) covers what they add locally.

Git pushes use the editor's forwarded credentials. The GitHub CLI is installed but authenticates separately: a `GH_TOKEN` exported on the host is passed through, otherwise run `gh auth login` once inside the container. Neither is needed to publish a release, which runs in GitHub Actions over OIDC.

## Contribution workflow

1. Fork the repository and create a focused branch from `main`.
2. Add or update tests before changing behavior.
3. Keep provider-specific objects behind their adapter boundary.
4. Run the complete local validation suite shown above.
5. Add a concise entry under `Unreleased` in `CHANGELOG.md` for user-visible changes.
6. Sign off every commit with `git commit -s`.
7. Open a pull request using the repository template and respond to review feedback.

Suggested branch names include `fix/short-description`, `feat/provider-name`, and `docs/topic`.

## Pull requests

Keep changes focused, add tests, update documentation, and add a changelog entry when behavior changes. Draft pull requests are welcome for early technical feedback, but a pull request should be marked ready only when it is reviewable and CI passes.

Reviews consider correctness, security, canonical-contract stability, provider capability honesty, test quality, documentation, and long-term maintenance cost. Maintainers may ask that unrelated changes be split into separate pull requests.

By contributing, you certify the [Developer Certificate of Origin 1.1](https://developercertificate.org/); add `Signed-off-by: Your Name <email>` to commits with `git commit -s`.

Provider adapter PRs must document:

- official API documentation and authentication;
- models and lifecycle state;
- URL/upload delivery support;
- languages, diarization, timestamps, language detection, code switching, hints, and style support;
- maximum bytes/duration and known rate limits;
- versioned pricing source;
- request translation, response normalization, and error contract tests.

Do not simulate unsupported capabilities. No provider-native object may escape an adapter.

AI-assisted contributions are welcome, but contributors remain responsible for every line submitted, its licensing, its tests, and the accuracy of any provider or security claim.

## Security reports

Follow [SECURITY.md](SECURITY.md). Never include exploitable security details in a public issue or pull request before coordinated disclosure.

## Review and merge policy

All changes to `main` go through pull requests. Required CI and security checks must pass, review conversations must be resolved, and maintainers use squash merging to keep a linear history. Approval does not guarantee merge: a contribution may be declined when it expands scope, weakens security, duplicates existing behavior, or creates disproportionate maintenance cost.
