# Privacy and retention

Defaults are audio retention zero, transcript retention zero, content-free logs, and no project telemetry. Inline transcripts exist only for request processing. Proxy audio is written to ephemeral storage only when a provider requires upload or the operator requests proxy mode, and is deleted after success or failure.

Temporary transcript storage is disabled by default. When explicitly enabled, `result_mode=stored` writes only canonical transcript JSON, never audio, signed source URLs, or provider credentials. Configure a 24-hour TTL and an object-storage lifecycle rule; application TTL checks do not replace bucket lifecycle deletion. `delete_transcript` is idempotent.

Providers receive either the original signed URL or proxied audio according to `source_delivery`. Passthrough minimizes OpenTranscribe retention and bandwidth but discloses the URL to the chosen provider. Proxy hides the URL but causes OpenTranscribe to process temporary audio bytes. Operators must choose based on their data-processing agreements and threat model.

Provider-side retention is governed by the operator's provider account and contract. Enabling OpenTranscribe zero-retention behavior cannot create a provider entitlement that the account does not have.
