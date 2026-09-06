# Contributing

Thank you for improving OpenTranscribe. Provider adapters, security hardening, compatibility fixes, deployment recipes, benchmarks, and documentation are especially welcome.

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

Python 3.12 is required. Never commit `.env`, provider credentials, signed URLs, personal recordings, or real transcript content.

## Pull requests

Keep changes focused, add tests, update documentation, and add a changelog entry when behavior changes. CI must pass. By contributing, you certify the [Developer Certificate of Origin 1.1](https://developercertificate.org/); add `Signed-off-by: Your Name <email>` to commits with `git commit -s`.

Provider adapter PRs must document:

- official API documentation and authentication;
- models and lifecycle state;
- URL/upload delivery support;
- languages, diarization, timestamps, language detection, code switching, hints, and style support;
- maximum bytes/duration and known rate limits;
- versioned pricing source;
- request translation, response normalization, and error contract tests.

Do not simulate unsupported capabilities. No provider-native object may escape an adapter.

## Security reports

Follow [SECURITY.md](SECURITY.md). Never include exploitable security details in a public issue or pull request before coordinated disclosure.
