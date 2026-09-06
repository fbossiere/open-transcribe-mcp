## Summary

<!-- Explain the problem and the approach. Keep the change focused. -->

## Related issue

<!-- Use "Closes #123" when this PR should close an issue. -->

## Changes

-

## Validation

<!-- List the exact commands, tests, or manual checks you ran. -->

- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy src`
- [ ] `uv run pytest --cov=open_transcribe`

## Security and privacy

- [ ] I did not include credentials, signed URLs, real recordings, or transcript content.
- [ ] I considered SSRF, authentication, retention, logging, and untrusted transcript input where relevant.
- [ ] New or changed provider behavior has contract tests and documents capability limits.

## Documentation and compatibility

- [ ] I updated user-facing documentation and `CHANGELOG.md` when behavior changed.
- [ ] I called out any schema, configuration, API, or deployment compatibility impact.

## Contributor declaration

- [ ] My commits include a `Signed-off-by` line (`git commit -s`) under the Developer Certificate of Origin 1.1.

