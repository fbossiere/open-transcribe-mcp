# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- An opt-in end-to-end suite, `tests/e2e`, that transcribes an audio file through a deployed instance and verifies the returned transcript. It takes the deployment URL in any of its Terraform output forms, negotiates the request against the models the deployment reports as configured, reads stored results back through the chunk tool and deletes them, and keeps transcript text out of its output. It skips unless a deployment URL is given, so an ordinary test run is unchanged.
- The Scaleway deployment guide now states the IAM permission sets the Terraform key needs, with their project or organization scope, the console and `scw` procedures that create the application, policy, and key, and how the credentials reach Terraform and an S3 state backend. It also records that a bucket policy naming only the result-store application locks a non-owner deployment key out of the bucket.
- The dev container's TFLint and Terragrunt are documented: how TFLint complements the CI Terraform job, and an optional Terragrunt wrapper carrying the remote state backend the module does not hardcode.

### Changed

- The dev container installs TFLint 0.64.0 and Terragrunt 1.1.4 alongside the pinned Terraform.

## [1.1.0] - 2026-09-07

### Added

- A dev container reproducing the CI toolchain: pinned `uv`, Python 3.12, Docker, Terraform, the GitHub CLI, and the fixture-generation audio tools.
- Provider `Retry-After` headers are now honoured between retries, in both the delay-seconds and HTTP-date forms, bounded so a distant or hostile hint cannot hold a request open.

### Fixed

- A malformed source URL is now rejected as `SOURCE_URL_REJECTED`. An empty, overlong, or unmappable IDNA label escaped as a raw `UnicodeError`, and a malformed bracketed authority or a netloc failing NFKC normalization escaped as a raw `ValueError`, so a bad URL was reported as an internal error rather than a rejected source. A hostname that normalizes to nothing is rejected rather than accepted as empty.
- URL redaction and source log fields no longer raise on a URL they cannot parse, which a hostile redirect target could previously trigger inside an error path; an unparseable URL degrades to a placeholder instead of being echoed.
- Provider rate limits are now reported as `RATE_LIMITED`. The code was documented in the error model but unreachable, because a `429` was classified as a generic transient failure and surfaced as `PROVIDER_UNAVAILABLE` once retries were exhausted.

### Security

- `.gitignore` and `.dockerignore` now cover every `.env.*` variant rather than `.env` alone, so a local credential file such as `.env.local` can no longer be staged by a bulk `git add` or reach a build context. `.env.example` stays tracked.

## [1.0.0] - 2026-09-07

### Added

- DNS-rebinding-resistant proxy downloads that connect only to the validated public address while preserving HTTPS SNI and Host routing.
- Groq URL passthrough and complete word-plus-segment timestamp requests.
- Strict MkDocs documentation builds, dependency auditing, filesystem/container scanning, and release artifact inspection.
- A redistributable two-voice English/French synthetic audio fixture, reference transcript, and runnable demo default.
- Strictly built documentation published on GitHub Pages.
- Public GHCR images with OCI provenance, a CycloneDX SBOM, release checksums, and an immutable GitHub release.

### Changed

- ElevenLabs requests now default to the provider's zero-retention mode.
- Unexpected result-store and provider failures are returned as content-free project errors without logging exception payloads.
- Production-oriented Terraform for Scaleway Serverless Containers, including a private registry, scale-to-zero defaults, probes, secret validation, and optional least-privilege temporary Object Storage.
- Terraform formatting and validation in CI.
- The production Docker image now includes the optional S3 result-store dependency.
- The development lock now requires a non-vulnerable pytest release.
- Container builds install the project non-editably so the runtime image is independent of builder source paths.
- Scaleway provider selection is committed and enforced as read-only in CI.

### Security

- Proxy connections are pinned to the DNS addresses that passed SSRF validation, including after redirects.

## [0.1.1] - 2026-09-06

### Fixed

- Trigger registry publishing from the version tag before creating an immutable GitHub release.

### Added

- structured issue forms, pull-request template, code ownership, governance, and support policy;
- pinned GitHub Actions workflows for quality checks, builds, CodeQL, and dependency review;
- weekly Dependabot updates for Python and GitHub Actions dependencies.
- automated, OIDC-based publishing to PyPI and the official MCP Registry for GitHub releases;
- installable MCP Registry metadata and release-version validation.

## [0.1.0] - 2026-09-06

### Added

- stateless FastMCP Streamable HTTP server with five-tool public surface;
- canonical transcript, capability, pricing, result, and stable error schemas;
- Microsoft MAI-Transcribe-2, ElevenLabs Scribe v2, and Groq Whisper adapters;
- default, fixed, quality, cost, and latency routing with observable transient fallback;
- HTTPS URL passthrough and bounded proxy download with SSRF and redirect controls;
- constant-time bearer authentication and content-free structured logging;
- disabled-by-default retention plus signed-cursor memory and S3-compatible temporary stores;
- Docker, Scaleway, provider, privacy, security, Plaud, and ChatGPT/Drive documentation;
- unit, provider contract, security, and MCP transport tests plus release CI.

[Unreleased]: https://github.com/fbossiere/open-transcribe-mcp/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/fbossiere/open-transcribe-mcp/releases/tag/v1.1.0
[1.0.0]: https://github.com/fbossiere/open-transcribe-mcp/releases/tag/v1.0.0
[0.1.1]: https://github.com/fbossiere/open-transcribe-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/fbossiere/open-transcribe-mcp/tree/v0.1.0
