# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Production-oriented Terraform for Scaleway Serverless Containers, including a private registry, scale-to-zero defaults, probes, secret validation, and optional least-privilege temporary Object Storage.
- Terraform formatting and validation workflow.
- structured issue forms, pull-request template, code ownership, governance, and support policy;
- pinned GitHub Actions workflows for quality checks, builds, CodeQL, and dependency review;
- weekly Dependabot updates for Python and GitHub Actions dependencies.

### Changed

- The production Docker image now includes the optional S3 result-store dependency.

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

[Unreleased]: https://github.com/fbossiere/open-transcribe-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/fbossiere/open-transcribe-mcp/releases/tag/v0.1.0
