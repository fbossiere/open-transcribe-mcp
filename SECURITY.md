# Security policy

## Supported versions

Security fixes are provided for the latest `0.1.x` release. Until OpenTranscribe reaches 1.0, users should treat every minor release as potentially contract-changing and keep deployments current.

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability. Use [GitHub private vulnerability reporting](https://github.com/fbossiere/open-transcribe-mcp/security/advisories/new). If that channel is unavailable, contact the maintainer through the private address listed on the GitHub profile and request an encrypted reporting channel; do not include exploit details in the first message.

We aim to acknowledge reports within three business days, provide an initial assessment within seven business days, and coordinate disclosure after a fix is available. Please allow reasonable remediation time before publication.

High-severity examples include:

- SSRF or redirect-validation bypass;
- MCP authentication bypass;
- provider API-key, bearer-token, or signed-URL leakage;
- cross-user transcript access;
- persistent or unintended audio/transcript retention;
- a way for transcript content to trigger tool execution or change routing.

## Security model

OpenTranscribe is designed for single-tenant self-hosting. Bearer authentication protects `/mcp`; health probes are intentionally public and contain no secrets. Provider credentials exist only in server-side configuration.

Audio URLs are untrusted. The server requires HTTPS by default, rejects non-global addresses, validates DNS before each request and every redirect, limits redirects/bytes/time, disables environment proxy inheritance, validates media type or file signature, and deletes proxy files after use. Host allow-listing and egress firewall rules are recommended for high-assurance deployments because application-level DNS validation cannot replace network policy.

Transcript text is also untrusted. This service normalizes and returns content but never interprets it as instructions. Downstream LLM systems must apply their own prompt-injection defenses.

Logs must never contain audio, transcript text, complete source URLs, query parameters, authorization headers, API keys, or phrase-hint contents.

See [docs/security.md](docs/security.md) for the threat model and controls.
