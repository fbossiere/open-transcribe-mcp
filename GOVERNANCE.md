# Governance

OpenTranscribe uses lightweight, maintainer-led governance. The goal is to make decisions transparent without imposing process that is disproportionate to the project's current size.

## Roles

- **Contributors** report issues, improve documentation, review changes, and submit pull requests.
- **Maintainers** triage work, review and merge changes, manage releases, respond to security reports, and protect the project's scope and compatibility.
- **The lead maintainer**, currently [@fbossiere](https://github.com/fbossiere), has final responsibility for project direction, security decisions, releases, and adding or removing maintainers.

Maintainer status is earned through sustained, constructive contributions and sound judgment, especially around security, provider contracts, and backwards compatibility.

## Decision process

Small fixes are decided in their pull requests. Substantial changes must begin with a feature issue before implementation. Examples include:

- canonical schema or MCP tool changes;
- new providers or delivery modes;
- authentication, storage, retention, or network-policy changes;
- new required infrastructure or dependencies;
- backwards-incompatible configuration or deployment changes.

Maintainers seek rough consensus based on user value, scope, security, interoperability, maintenance cost, and evidence from official provider documentation. When consensus is not possible, the lead maintainer records the decision and its rationale in the issue or pull request.

## Releases and compatibility

Releases follow Semantic Versioning. Before 1.0, minor versions may change public contracts, but changes must be documented in `CHANGELOG.md` and accompanied by migration guidance when practical. Security releases may use an abbreviated private process before coordinated disclosure.

## Changes to governance

Governance changes use the same pull-request process as code changes and should explain the problem being solved.

