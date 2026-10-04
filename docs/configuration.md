# Configuration and service combinations

This guide describes the released **1.2.1** settings and the Scaleway root module. Choose your
hosting mode, provider credentials, MCP authentication and result storage independently.
A provider key pays for transcription; it is never the credential a client uses to access MCP.

## Where configuration lives

| Installation | Settings | Secrets | Apply a change |
| --- | --- | --- | --- |
| Python HTTP server | `OT_*` environment variables, or `.env` in the working directory | Environment or private `.env` | Restart the process |
| Docker HTTP server | Inject `OT_*` through the container environment or `--env-file` | Container secret injection or private environment file | Recreate the container |
| Scaleway with Terraform | `infra/scaleway/terraform.tfvars` | `secret_environment_variables` | Review `terraform plan`, then apply |
| Managed Linux desktop / STDIO | Setup's versioned TOML file passed with `--config` | Secret Service keyring; TOML holds references | Apply through Setup and restart the client-owned engine |

For the ordinary HTTP command, environment variables override `.env`, which overrides built-in
defaults. Programmatic `Settings(...)` arguments take precedence over both. `.env.local` is not
loaded by the ordinary command; the live Groq tests load it explicitly. Managed desktop mode
ignores ambient `OT_*` and `.env` and accepts only its managed settings and keyring references.

Settings use `OT_` and `__` for nesting: `OT_GROQ__API_KEY`, for example. Lists such as
`OT_SECURITY__ALLOWED_SOURCE_HOSTS` use JSON, for example `["media.example.com"]`.
[`.env.example`](https://github.com/fbossiere/open-transcribe-mcp/blob/main/.env.example) is a
settings inventory. Omit unused entries when making your runtime file: an empty URL or number
is not the same as an unset value, and an empty key can still appear configured.
Never copy that inventory unchanged and assume it is a working provider configuration.

`config/routing.yaml` contains quality/latency rankings and `config/pricing.yaml` contains
informational prices. These are bundled with the package; `OT_CONFIG_DIR` can select a custom
metadata directory. Editing a ranking does not add a provider adapter or grant capabilities.

## Choose one or more transcription providers

Only configured adapters participate in hosted routing. Adding another key makes another
provider available; it does not disable the existing one. Set the default provider **and** its
matching model together. The defaults are a preference among compatible models, not a rule
that prevents a caller from selecting another configured provider.

| Available service | Required secret | Additional setting | Matching default model | Speaker diarization |
| --- | --- | --- | --- | --- |
| Microsoft | `OT_MICROSOFT__API_KEY` | `OT_MICROSOFT__ENDPOINT` | `MAI-Transcribe-2` | Supported |
| ElevenLabs | `OT_ELEVENLABS__API_KEY` | Account must support the selected retention mode | `scribe-v2` | Supported |
| Groq | `OT_GROQ__API_KEY` | None; standard API endpoint is built in | `whisper-large-v3` or `whisper-large-v3-turbo` | Not supported |
| Any combination | Each selected service's own key | Microsoft still needs its endpoint; ElevenLabs still needs retention eligibility | One default provider/model pair | Filtered per request |

The following are **alternative minimal `.env` files**, not blocks to concatenate unchanged.
Replace the example credentials and protect the resulting file with `chmod 600 .env`.
Use an actual Speech resource endpoint for Microsoft. Each file starts an authenticated HTTP
server locally; run it behind HTTPS when hosting remotely.

### Groq only

```dotenv
OT_ENVIRONMENT=prod
OT_HOST=127.0.0.1
OT_DEFAULT_PROVIDER=groq
OT_DEFAULT_MODEL=whisper-large-v3-turbo
OT_GROQ__API_KEY=replace-with-your-groq-key
OT_SECURITY__AUTH_MODE=bearer
OT_SECURITY__BEARER_TOKEN=replace-with-a-long-random-value
OT_RESULT_STORE__BACKEND=disabled
```

Use `transcript_style=verbatim`. An explicit request for diarization or clean style is rejected
with strict capability checking. An ordinary request with those fields omitted works.

### ElevenLabs only

```dotenv
OT_ENVIRONMENT=prod
OT_HOST=127.0.0.1
OT_DEFAULT_PROVIDER=elevenlabs
OT_DEFAULT_MODEL=scribe-v2
OT_ELEVENLABS__API_KEY=replace-with-your-elevenlabs-key
OT_ELEVENLABS__ZERO_RETENTION=true
OT_SECURITY__AUTH_MODE=bearer
OT_SECURITY__BEARER_TOKEN=replace-with-a-long-random-value
OT_RESULT_STORE__BACKEND=disabled
```

The ElevenLabs key needs **Speech to Text → Access**. Other endpoint permissions are not needed
for this adapter. A present key is not proof of correct permissions, balance or model access.
`list_transcription_models(configured_only=true)` and `/readyz` report configuration presence;
verify access with a short authorized transcription.

OpenTranscribe sends zero-retention requests by default. ElevenLabs reserves this option for
eligible Enterprise customers; see its [zero-retention documentation](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode)
and [transcription API](https://elevenlabs.io/docs/api-reference/speech-to-text/convert).
For a standard account, change `OT_ELEVENLABS__ZERO_RETENTION` to `false` **only after explicitly
accepting provider-side logging and retention**. Keeping it `true` on an ineligible account can
make transcription fail. This provider option is independent of OpenTranscribe's result store.

### Microsoft only

```dotenv
OT_ENVIRONMENT=prod
OT_HOST=127.0.0.1
OT_DEFAULT_PROVIDER=microsoft
OT_DEFAULT_MODEL=MAI-Transcribe-2
OT_MICROSOFT__ENDPOINT=https://YOUR-RESOURCE.cognitiveservices.azure.com
OT_MICROSOFT__API_KEY=replace-with-your-microsoft-key
OT_SECURITY__AUTH_MODE=bearer
OT_SECURITY__BEARER_TOKEN=replace-with-a-long-random-value
OT_RESULT_STORE__BACKEND=disabled
```

### ElevenLabs and Groq on Scaleway

Copy this to a private `terraform.tfvars`, fill the placeholders and choose the ElevenLabs
retention mode deliberately. Do not put real credentials in `terraform.tfvars.example`.

```hcl
project_id = "00000000-0000-0000-0000-000000000000"
region     = "fr-par"
image_tag  = "1.2.1"
auth_mode  = "bearer"

environment_variables = {
  OT_DEFAULT_PROVIDER           = "elevenlabs"
  OT_DEFAULT_MODEL              = "scribe-v2"
  OT_ELEVENLABS__ZERO_RETENTION = "true"
}

secret_environment_variables = {
  OT_SECURITY__BEARER_TOKEN = "replace-with-a-long-random-value"
  OT_ELEVENLABS__API_KEY    = "replace-with-your-elevenlabs-key"
  OT_GROQ__API_KEY          = "replace-with-your-groq-key"
}

enable_result_store = false
tags                = ["environment=production"]
```

To prefer Groq, change only `OT_DEFAULT_PROVIDER` to `groq` and `OT_DEFAULT_MODEL` to one of its
Whisper model names. Leave the ElevenLabs key to keep Scribe available for speaker turns.
To add Microsoft, add its key to the secrets map and its endpoint to the non-secret map.
Changing defaults or keys does not require rebuilding the image, but the container must be
redeployed with the updated environment.

In managed desktop mode, a stored key alone does **not** enable a provider. Setup must also
explicitly enable it. Cross-provider fallback and temporary audio relay are separate permissions,
both off by default. The [desktop guide](desktop.md) describes those controls.

## Defaults, explicit choices and fallback

Capability filtering happens before ranking. Call `list_transcription_models` to inspect the
capabilities of your deployed version.

| Request | Behavior |
| --- | --- |
| `provider=auto`, `routing_policy=default` | Prefer the configured default pair when it satisfies the request; otherwise select a compatible model |
| `provider=auto` with `quality`, `cost` or `latency` | Rank only compatible configured models; rankings/prices are metadata, not an accuracy guarantee |
| Explicit `provider` and `model` | Start with that configured model; transient fallback may still reach other compatible models when allowed |
| Explicit provider/model, `routing_policy=fixed`, `allow_fallback=false` | Use only that model |
| `model` with `provider=auto`, or fixed routing with `provider=auto` | Invalid request |
| `diarization=true`, `strict_capabilities=true` | Require real speaker diarization; exclude both Groq models |
| Capability omitted / `null` | Bind it to the selected model's supported defaults and report the effective value in metadata |
| `strict_capabilities=false` | Permit capability downgrades and return warnings naming the dropped requirements |

Hosted requests default to `allow_fallback=true`. A second compatible provider can receive the
audio after a transient timeout, network error, 429 or 5xx. Set `allow_fallback=false` when only
one recipient is permitted. Fallback does not correct authentication errors, invalid input,
unsupported capabilities or rejected source URLs. Managed desktop policy can further restrict
fallback to models within the chosen provider even when the request allows fallback.

For a French conversation, explicitly request `language=fr`, `diarization=true`, segment
timestamps and strict capabilities. See the complete [Scribe speaker-turn recipe](providers.md#french-conversations-with-speaker-turns).
Speaker labels such as `SPEAKER_01` distinguish voices within a transcript; they never identify
people. Render `segments`, because the flat `text` field does not preserve speaker turns.

## MCP authentication is a separate choice

All provider combinations work with either supported HTTP authentication mode.

| Transport and mode | Client credential | Server configuration |
| --- | --- | --- |
| HTTP, bearer | Shared deployment token in `Authorization: Bearer …` | `OT_SECURITY__AUTH_MODE=bearer` and `OT_SECURITY__BEARER_TOKEN` |
| HTTP, OIDC | User access token issued by your external identity provider | OIDC URLs, required scope and entitlement claim; no shared MCP bearer secret needed |
| Managed STDIO | Local user/process boundary | Setup configuration and keyring; no network endpoint or OAuth server |

For Terraform, use the top-level `auth_mode = "bearer"` or `"oidc"` input. The module sets
`OT_SECURITY__AUTH_MODE` itself; putting a different value in `environment_variables` cannot
override it. OIDC mode excludes `OT_SECURITY__BEARER_TOKEN` from the runtime secrets map.
Provider keys are still required in OIDC mode.

For OIDC, keep your provider settings and add this complete authentication block to the
non-secret map, with `auth_mode = "oidc"`:

```hcl
# Add these entries inside your existing environment_variables map.
OT_SECURITY__OIDC_ISSUER_URL           = "https://id.example.com/realms/transcribe"
OT_SECURITY__OIDC_JWKS_URL             = "https://id.example.com/realms/transcribe/protocol/openid-connect/certs"
OT_SECURITY__OIDC_PUBLIC_BASE_URL      = "https://transcribe.example.com"
OT_SECURITY__OIDC_REQUIRED_SCOPE       = "mcp:tools"
OT_SECURITY__OIDC_REQUIRED_CLAIM_PATH  = "realm_access.roles"
OT_SECURITY__OIDC_REQUIRED_CLAIM_VALUE = "open-transcribe-user"
```

The public base URL is the HTTPS **origin**, without `/mcp`. Tokens must contain the configured
issuer, an exact audience of `https://transcribe.example.com/mcp`, valid expiry, the required
scope and the entitlement claim. Configure your identity provider and client together following
[OIDC authentication](auth-oidc.md). OpenTranscribe validates tokens; it does not host Keycloak
or issue OAuth tokens. Unauthenticated HTTP is rejected in production.

If a new Scaleway container has no known public URL yet, deploy first with bearer authentication,
read `container_endpoint`, configure the identity provider for that origin and `/mcp` audience,
then switch to OIDC in a reviewed Terraform update. Preserve the OIDC values when changing
provider defaults or keys on an existing deployment.

## Result storage and provider retention are independent

| Combination | Result behavior | Appropriate deployment |
| --- | --- | --- |
| `backend=disabled` + inline response | No retained transcript in OpenTranscribe | Default; works with scale-to-zero |
| `backend=disabled` + `result_mode=stored` | Explicit rejection | Enable a store first |
| `backend=memory` + cursor secret | Temporary process-local transcript chunks | Local/test only; lost on restart and inaccessible from another instance |
| `backend=s3` + cursor secret, bucket and credentials | Shared, TTL-bound transcript chunks and explicit deletion | Stateless, scaled HTTP deployments |
| Any store + ElevenLabs zero retention | Provider eligibility still required | Application storage does not grant Enterprise features |
| Disabled store + ElevenLabs standard mode | OpenTranscribe retains no transcript, but provider-side retention is enabled | Requires explicit operator acceptance |

`result_mode=auto` uses inline output until configured size/segment limits require storage; with
the store disabled, such a large result fails rather than being truncated or silently retained.
`result_mode=inline` still has a hard response byte limit. Storage does not create a transcript
library or remove the request's need for an authorized audio source.

On Scaleway, `enable_result_store=false` forces the disabled backend. To enable shared storage,
set `enable_result_store=true`, add `OT_RESULT_STORE__CURSOR_SECRET` to the secrets map, and choose
`result_ttl_seconds` (60–604800 seconds in this module; default 86400). Terraform provisions the
bucket, lifecycle policy and runtime S3 identity and injects the S3 settings and `AWS_*` keys.
Keep the [result-store IAM and bucket-policy caveat](deploy-scaleway.md#optional-temporary-result-store)
in mind before enabling it. The module does not offer a memory backend.

Outside Terraform, install the `s3` extra and configure `OT_RESULT_STORE__BACKEND=s3`, a cursor
secret, `OT_RESULT_STORE__S3_BUCKET`, endpoint/region/prefix settings and S3 `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` credentials. See [privacy and retention](privacy.md).

A Terraform **state bucket** is a separate infrastructure concern. It stores deployment state,
not transcript chunks; using a remote state backend does not enable the result store. Do not
apply transcript TTL deletion rules to the state bucket.

## Keep the different secrets in the right place

| Secret | Purpose | Where it belongs |
| --- | --- | --- |
| `SCW_ACCESS_KEY`, `SCW_SECRET_KEY` | Terraform and image registry deployment | Deployer's environment / CI secret store |
| Provider `OT_*__API_KEY` | STT provider calls | Server secrets; Terraform `secret_environment_variables` |
| `OT_SECURITY__BEARER_TOKEN` | Shared MCP client authentication | Server secrets and trusted client configuration, only in bearer mode |
| OIDC signing keys / client secrets | Identity-provider and OAuth client operation | Identity provider / client; OpenTranscribe uses public JWKS |
| `OT_RESULT_STORE__CURSOR_SECRET` | Signing stored-result cursors | Server secrets when a result store is enabled |
| Runtime S3 `AWS_*` keys | Temporary transcript object access | Server secret environment; generated by this Terraform module |
| Backend S3 `AWS_*` keys | Remote Terraform state access | Deployer's backend environment; separate from runtime credentials |

Terraform merges your non-secret map with enforced production settings: HTTP authentication mode,
HTTPS audio sources, private-network rejection, port 8000, container timeout and chosen store.
Use the module inputs for these settings; an environment-map override is not authoritative.
Secret-looking names are rejected in the non-secret map. Keep placeholders in tracked examples;
keep your real values in the ignored `terraform.tfvars` and inject provider keys only server-side.

`secret_environment_variables` redacts normal Terraform output but does not encrypt state or
saved plans. Protect `.env`, `terraform.tfvars`, state backups and plan files; use encrypted,
access-controlled remote state for shared production operations. The Terraform module injects
Scaleway container secret variables directly; it does not provision Secret Manager references.

## Verify a change

1. Restart the local server, recreate Docker, or plan/apply Terraform according to your mode.
2. Check `/healthz` and `/readyz` for HTTP deployments. Ready means a key is present, not that the
   provider has accepted it. STDIO uses Setup/`doctor`, not those network probes.
3. With an authenticated client, call `list_transcription_models(configured_only=true)`.
4. Run a short authorized audio test with the required capabilities and no fallback to confirm
   the intended provider. Provider charges apply; do not use personal recordings as CI fixtures.
5. If storage is enabled, read the result chunks and delete the temporary transcript.

| Symptom | First checks |
| --- | --- |
| `PROVIDER_AUTHENTICATION_FAILED` | Correct provider key, permissions (ElevenLabs Speech to Text), account eligibility |
| `UNSUPPORTED_CAPABILITY` | Requested diarization/style against the selected model; keep strict checking if the requirement matters |
| `RESULT_STORE_DISABLED` | Stored/oversized output with no store; enable S3 deliberately or use smaller inputs |
| HTTP 401 at `/mcp` | MCP bearer token or OIDC issuer/audience/scope/claim; this is independent of the STT key |
| Startup validation failure | Empty typed settings, missing authentication, incomplete OIDC or result-store configuration |
| Terraform keeps changing only memory/storage | Scaleway rounds allocations to integer decimal MB; use the observed byte values for those module inputs |

See the [Scaleway operational checks](deploy-scaleway.md#operational-checks) and the
[publication protocol](releasing.md) for deployment and release procedures.
