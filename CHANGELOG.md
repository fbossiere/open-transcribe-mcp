# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **A Linux desktop distribution.** `open-transcribe-assistant_<version>-<revision>_amd64.deb` bundles the Python runtime, the transcription engine, and a native PySide6 setup application, so a user can install from a file manager, add a provider key, and connect a local MCP client without Python, `uv`, or editing configuration files. The release publishes the package with a SHA-256 checksum, a CycloneDX SBOM, a provenance record, and a GitHub build attestation tied to the artifact digest and source revision. Documented in `docs/desktop.md`; its evidence sheet is `docs/desktop-acceptance.md`, where every scenario starts at *Not tested*.
- **A local STDIO transport.** `open-transcribe-mcp serve --transport stdio --config <path>` runs one client-owned engine process that opens no network socket and uses stdout exclusively for MCP messages. Startup validation is now transport-aware: STDIO is authenticated by the local process and session boundary and refuses a bearer token, while HTTP keeps its existing authenticated, stateless contract unchanged. Both transports build the same services and expose the same five tools.
- **A managed desktop configuration mode.** Settings live in a closed, versioned TOML schema under `$XDG_CONFIG_HOME/open-transcribe-mcp/desktop/`, written atomically under a per-installation lock with ownership and permission checks made on opened descriptors. Provider keys live in Secret Service and are resolved inside the engine; the configuration holds references, never values. Managed mode ignores ambient `OT_*` variables and a working-directory `.env`, so a client-launched engine cannot be steered by the shell that started the client.
- **Engine-enforced authorization policy.** `TranscriptionPolicy` gates the router before ranking, the service before every provider attempt, and the source broker before any download. A stored key does not enable a provider, cross-provider fallback is a separate permission that is off by default, and temporary audio processing is a separate permission that is off by default. Two new normalized codes report these: `PROVIDER_NOT_ENABLED` and `TEMPORARY_AUDIO_NOT_PERMITTED`.
- **A temporary-audio lifecycle for desktop relay.** When the permission is granted, relayed audio goes to a verified private runtime directory with unpredictable names, exclusive creation, per-file and aggregate bounds, and an expiry of at most one hour. Files are swept at least every five minutes while the session runs, reclaimed when their owning process dies or the machine reboots, and cleaned before reuse on the next session. An optional per-user `systemd` timer performs the sweep; it makes no network call and is never installed from a maintainer script.
- **Setup services shared by the window and the command line.** `open-transcribe-mcp doctor --config <path> --json` emits the same typed diagnostic report the interface shows, with stable check identifiers and an allowlisted export that carries no credential, URL, endpoint name, home path, client configuration, or transcript text. `open-transcribe-mcp cleanup-temporary-audio` performs the sweep. Neither is reachable as an MCP tool.
- **Client registration adapters with a transactional apply.** Registration plans are reviewed before anything changes, credentials are written under fresh references so a failed key replacement preserves the working one, the exact packaged engine is verified against MCP before a client is told to launch it, and every phase records its intent and its observed result in a recovery journal. A registration this installation did not create is a conflict, never something to overwrite, and takeover is always explicit. `config/desktop/clients.toml` carries a per-client `support_status`; every shipped entry is `untested` until a real run is recorded.
- English and French interface strings, complete in both languages and never assembled by concatenation.

### Changed

- Operational logging now goes to stderr with an explicit stream and logger factory. stdout belongs to the MCP protocol under the STDIO transport, and structlog's default print logger would have written to it.
- `create_service` and `create_server` accept an authorization policy and a temporary-file factory. Both default to the existing unrestricted behaviour, so the hosted, container, and CLI deployments are unchanged.
- The Python package gains a `managed` extra (Secret Service support for the engine) and a `desktop` extra (Qt and the TOML writer for Setup). Neither is pulled in by the minimal server installation or the container image, and both are imported lazily.

### Added

- Opt-in local Groq integration tests with explicit `.env.local` loading, one shared synthetic-audio transcription, canonical output and timestamp checks, and a network-free unsupported-diarization check.
- An opt-in end-to-end suite, `tests/e2e`, that transcribes an audio file through a deployed instance and verifies the returned transcript. It takes the deployment URL in any of its Terraform output forms, negotiates the request against the models the deployment reports as configured, reads stored results back through the chunk tool and deletes them, and keeps transcript text out of its output. It skips unless a deployment URL is given, so an ordinary test run is unchanged.
- The Scaleway deployment guide now states the IAM permission sets the Terraform key needs, with their project or organization scope, the console and `scw` procedures that create the application, policy, and key, and how the credentials reach Terraform and an S3 state backend. It also records that a bucket policy naming only the result-store application locks a non-owner deployment key out of the bucket.
- The dev container's TFLint and Terragrunt are documented: how TFLint complements the CI Terraform job, and an optional Terragrunt wrapper carrying the remote state backend the module does not hardcode.
- A step-by-step tutorial for transcribing a Plaud recorder on Ubuntu, written for readers who do not write code, published on the documentation site and as a PDF. `scripts/build_tutorial_pdf.py` renders the PDF from the same Markdown source.
- `examples/plaud_transcribe.py`, which transcribes a local audio file by publishing it on a loopback-only server for the duration of one `proxy`-delivery request and writing a readable transcript beside the audio.

### Security

- Apply available Debian package fixes in a shared Docker base stage so the builder and runtime do not retain vulnerabilities patched after the pinned Python image was published.

### Changed

- `diarization`, `timestamps`, and `transcript_style` are now unset by default instead of requesting diarization, segment timestamps, and clean output. An unset capability is bound to what the selected model supports and reported in the response metadata, so a request naming only its audio source now succeeds on a deployment whose only provider is Groq, which previously answered `UNSUPPORTED_CAPABILITY` to the tool's own defaults. A stated capability still excludes every model that cannot honour it. The quickstart example and `examples/transcribe.py` no longer state the three capabilities, so they run against any single configured provider.
- `strict_capabilities=false` now downgrades under `provider=auto`. It only relaxed an explicitly named provider, so the flag was inert on the request shape that needs it most. The dropped capability is named in a `requested_capability_not_supported:*` warning, and the provider is asked only for what its model does, as it already was for a named provider.
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
