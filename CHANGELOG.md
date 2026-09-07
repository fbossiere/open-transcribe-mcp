# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/fbossiere/open-transcribe-mcp/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/fbossiere/open-transcribe-mcp/releases/tag/v1.0.0
[0.1.1]: https://github.com/fbossiere/open-transcribe-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/fbossiere/open-transcribe-mcp/tree/v0.1.0
