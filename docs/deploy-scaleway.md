# Deploy on Scaleway Serverless Containers

The reference target is **Scaleway Serverless Containers**, not Cloud Functions.

OpenTranscribe is a containerized ASGI service exposing MCP Streamable HTTP. Serverless Containers runs the existing OCI image and HTTP process directly, supports long requests and scale-to-zero, and does not require a function-specific handler or packaging model.

The Terraform root module is in [`infra/scaleway`](https://github.com/fbossiere/open-transcribe-mcp/tree/main/infra/scaleway). It provisions a private Container Registry namespace, a Serverless Containers namespace, the application container, and optional TTL-bound Object Storage.

## Reference sizing

The defaults intentionally start small:

- region: `fr-par`;
- scale: 0 to 3 instances;
- CPU: 500 mvCPU;
- memory: 512 MiB;
- ephemeral storage: 1 GiB;
- scale-out threshold: 4 concurrent requests per instance;
- one Uvicorn worker per instance;
- request timeout: 900 seconds;
- HTTPS-only ingress with application-level bearer authentication.

The concurrency value is an autoscaling threshold, not a hard request limit. Measure real recordings and provider latency before raising it. Provider and platform duration limits still apply.

## Prerequisites

- Terraform 1.11 or newer; the dev container and CI both pin 1.16.1;
- Docker with BuildKit/buildx;
- a Scaleway Project, preferably dedicated to this deployment;
- a Scaleway API key carrying the permission sets in [1. Create the deployment API key](#1-create-the-deployment-api-key);
- at least one transcription-provider credential.

The dev container also pins TFLint 0.64.0 and Terragrunt 1.1.4. Neither is required to deploy; see [Linting and Terragrunt](#linting-and-terragrunt).

## 1. Create the deployment API key

Terraform authenticates as a Scaleway **IAM application**, not as a human account. Create a dedicated application so the deployment identity can be scoped, audited, and rotated without touching anyone's personal access.

### Permission sets the key needs

| Permission set | Scope | Needed for | Required |
| --- | --- | --- | --- |
| `ContainerRegistryFullAccess` | Project | `scaleway_registry_namespace`, plus the `docker login` and `docker push` in step 3 | always |
| `ContainersFullAccess` | Project | `scaleway_container_namespace` and `scaleway_container` | always |
| `ObjectStorageFullAccess` | Project | the result bucket, its ACL, lifecycle rules, and bucket policy | `enable_result_store = true`, and any remote state bucket |
| `IAMManager` | Organization | the result-store IAM application, its policy, and its API key | `enable_result_store = true` |

The scope column is not a preference. The three product permission sets are attached to a policy rule listing your deployment project; `IAMManager` can only be attached to a rule scoped to the whole Organization, so it cannot be confined to the project the deployment lives in.

`IAMManager` also carries every `ProjectManager` permission and lets its holder write policies granting itself anything else in the Organization. Keep it out of routine deployments. Two keys separate the escalation from the delivery path:

- a **bootstrap key** holding all four permission sets, used interactively for the runs that create or replace the result-store identity;
- a **delivery key** holding only the three project-scoped sets, used for image pushes and container updates. It can plan and apply everything except the `scaleway_iam_*` resources.

With `enable_result_store = false` the delivery key is the only key needed, and no organization-scoped rule is required at all.

Two permission sets that look relevant are not: the container is `public` at the platform layer, so `ContainersPrivateAccess` is unnecessary, and the module creates no Secret Manager resources, so `SecretManagerFullAccess` is unnecessary.

If you prefer granular Object Storage rights over `ObjectStorageFullAccess`, the module's bucket resources need `ObjectStorageBucketsRead`, `ObjectStorageBucketsWrite`, `ObjectStorageBucketsDelete`, and `ObjectStorageBucketPolicyFullAccess`. Object-level sets are not needed for the deployment itself, because the runtime identity writes the transcripts and `force_destroy` is `false`. A remote state bucket is different: the S3 backend reads and writes state objects, so it also needs `ObjectStorageObjectsRead`, `ObjectStorageObjectsWrite`, and `ObjectStorageObjectsDelete` in whichever project holds that bucket.

### Create it in the console

1. **IAM** > **Applications** > **Create application**, for example `open-transcribe-deployer`.
2. **IAM** > **Policies** > **Create policy**, attached to that application. Add one rule scoped to the deployment project carrying the project-scoped permission sets, and, only when the result store is enabled, a second rule scoped to the Organization carrying `IAMManager`.
3. Open the application, then **API keys** > **Generate an API key**. Set an expiration date, set the deployment project as the key's preferred Project, and copy the secret key immediately: it is displayed once.

### Or create it with the CLI

`scw` is not part of the dev container; install it separately to use this path.

```bash
ORGANIZATION_ID="..."
PROJECT_ID="00000000-0000-0000-0000-000000000000"

APPLICATION_ID="$(scw iam application create \
  name=open-transcribe-deployer \
  description="Terraform deployment identity for OpenTranscribe MCP" \
  organization-id="$ORGANIZATION_ID" \
  -o template="{{ .ID }}")"

scw iam policy create \
  name=open-transcribe-deployer \
  description="Deploy the OpenTranscribe MCP Serverless Container" \
  application-id="$APPLICATION_ID" \
  organization-id="$ORGANIZATION_ID" \
  rules.0.project-ids.0="$PROJECT_ID" \
  rules.0.permission-set-names.0=ContainerRegistryFullAccess \
  rules.0.permission-set-names.1=ContainersFullAccess \
  rules.0.permission-set-names.2=ObjectStorageFullAccess
```

Add the organization-scoped rule only for the bootstrap key that has to create the result-store identity:

```bash
scw iam policy create \
  name=open-transcribe-bootstrap-iam \
  description="Create the OpenTranscribe MCP result-store identity" \
  application-id="$APPLICATION_ID" \
  organization-id="$ORGANIZATION_ID" \
  rules.0.organization-id="$ORGANIZATION_ID" \
  rules.0.permission-set-names.0=IAMManager
```

Then generate the key. Its `default-project-id` is what Object Storage uses when a request does not name a project, so point it at the deployment project:

```bash
scw iam api-key create \
  application-id="$APPLICATION_ID" \
  default-project-id="$PROJECT_ID" \
  expires-at="$(date -u -d '+90 days' +%Y-%m-%dT%H:%M:%SZ)" \
  description="OpenTranscribe MCP Terraform deployments"
```

### Hand the key to Terraform

The Scaleway provider reads its credentials from the environment. Export them in the shell that runs Terraform, and keep them out of `terraform.tfvars`, which is a file on disk that the module also fills with application secrets:

```bash
export SCW_ACCESS_KEY="SCW..."
export SCW_SECRET_KEY="..."
export SCW_DEFAULT_PROJECT_ID="00000000-0000-0000-0000-000000000000"
export SCW_DEFAULT_REGION="fr-par"
```

`SCW_ACCESS_KEY` is the key's access key, `SCW_SECRET_KEY` its secret key. `providers.tf` passes `project_id` and `region` explicitly from variables, so `SCW_DEFAULT_PROJECT_ID` and `SCW_DEFAULT_REGION` mainly serve the `scw` CLI and the `docker login` in step 3; `project_id` in `terraform.tfvars` must still match the project the key is scoped to.

An S3 remote state backend does not read `SCW_*`. It reads the AWS names, satisfied by the same Scaleway key:

```bash
export AWS_ACCESS_KEY_ID="$SCW_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$SCW_SECRET_KEY"
```

In CI, store the two `SCW_*` values as encrypted secrets, prefer a short-lived delivery key, and rotate on any suspected exposure. Deleting the IAM application revokes every key it issued.

## 2. Configure Terraform

```bash
cd infra/scaleway
cp terraform.tfvars.example terraform.tfvars
```

Set the real `project_id`, an immutable `image_tag`, provider configuration, a strong MCP bearer token, and provider credentials. Generate secrets locally, for example:

```bash
openssl rand -hex 32
```

Never commit `terraform.tfvars`, Terraform state, credentials, live signed URLs, recordings, or transcripts.

## 3. Bootstrap the private registry

The Serverless Container cannot be created before its image exists. Create the registry first:

```bash
terraform init
terraform apply -target=scaleway_registry_namespace.this
```

Read the exact image reference Terraform expects:

```bash
IMAGE_REFERENCE="$(terraform output -raw image_reference)"
REGISTRY_ENDPOINT="$(terraform output -raw registry_endpoint)"
```

Log in, build an AMD64 image, and push it:

```bash
printf '%s' "$SCW_SECRET_KEY" | docker login "$REGISTRY_ENDPOINT" --username nologin --password-stdin
docker buildx build --platform linux/amd64 --push --tag "$IMAGE_REFERENCE" ../..
```

The production image includes the `s3` optional dependency so the same immutable image can run with or without the optional result store.

## 4. Apply the complete deployment

Review a saved plan before applying:

```bash
terraform plan -out=open-transcribe.tfplan
terraform apply open-transcribe.tfplan
```

Terraform rejects empty secrets, missing MCP bearer authentication, and a configuration without any provider API key. It also forces production mode, HTTPS sources, public-URL SSRF protections, bearer authentication, and port 8000.

Get the endpoints:

```bash
terraform output -raw mcp_endpoint
terraform output -raw health_endpoint
```

The Scaleway container is `public` at the platform layer because MCP clients do not natively send Scaleway's private-container `X-Auth-Token`. OpenTranscribe's bearer middleware protects `/mcp`; `/healthz` remains available to the platform probe.

## Optional temporary result store

Set the following in `terraform.tfvars`:

```hcl
enable_result_store = true

secret_environment_variables = {
  OT_SECURITY__BEARER_TOKEN     = "..."
  OT_MICROSOFT__API_KEY          = "..."
  OT_RESULT_STORE__CURSOR_SECRET = "..."
}
```

Terraform then creates:

- a private Object Storage bucket;
- lifecycle deletion after the configured TTL rounded up to full days;
- a dedicated IAM application and API key;
- a bucket policy limited to list/get/put/delete under the transcript prefix;
- the S3 configuration and credentials injected into the container.

The application additionally enforces the exact TTL stored in object metadata. Bucket lifecycle is the cleanup backstop. Scale-to-zero is safe with the disabled and S3 stores; do not use the memory store with multiple instances or across cold starts.

IAM permission sets are project-scoped even though the bucket policy is prefix-scoped. A dedicated Scaleway Project prevents the result-store identity from inheriting access to unrelated buckets in the same project.

The bucket policy names only the result-store application. Scaleway evaluates a bucket policy in addition to IAM, and a principal that the policy does not name loses access to that bucket, whatever its IAM permission sets say; only the Organization owner keeps the inherent right to put and delete bucket policies. A deployment key that is an IAM application therefore cannot read the bucket's own configuration after `scaleway_object_bucket_policy.results` is applied, which breaks later plans and refreshes that touch the bucket. Run the result-store apply with an owner-held key, or extend the policy with a statement naming the deployment application, before enabling the store in a pipeline.

## Secrets and Terraform state

Scaleway Serverless Containers accepts secret environment variables, but its Terraform resource does not currently bind an environment variable to a Scaleway Secret Manager version. Terraform therefore receives the runtime secret values, and they can exist in state even though plans and CLI output redact them.

Use an encrypted remote state backend with tightly restricted access. Secret Manager resources alone would duplicate secrets without injecting them into the container or eliminating state exposure. Rotate the MCP token and provider keys if state is exposed.

## Linting and Terragrunt

The dev container pins Terraform 1.16.1, TFLint 0.64.0, and Terragrunt 1.1.4. CI runs only `terraform fmt -check -diff -recursive`, `terraform init -backend=false`, and `terraform validate`, so TFLint and Terragrunt are local tools, not merge gates.

TFLint checks the module with its bundled Terraform ruleset. Scaleway publishes no TFLint provider plugin, so it reviews module hygiene — unused declarations, naming, missing versions, deprecated syntax — rather than Scaleway resource arguments:

```bash
tflint --chdir=infra/scaleway --recursive
```

It reports nothing on the module as committed. Run it with `terraform fmt` and `terraform validate` before every plan; none of the three needs credentials or network access to Scaleway.

Terragrunt is optional and nothing in the repository requires it: `infra/scaleway` is a plain Terraform root module, and every command in this guide works without it. It earns its place when you want the remote state backend from the previous section committed rather than passed by hand, since the module deliberately hardcodes no backend. Terragrunt 1.1.4 invokes `terraform` by default in this container, so no `TG_TF_PATH` override is needed.

Keep the wrapper out of version control, or in an ignored path such as `infra/live/`, because it names your state bucket:

```hcl
# infra/live/terragrunt.hcl
terraform {
  source = "${get_repo_root()}/infra/scaleway"
}

remote_state {
  backend = "s3"

  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }

  config = {
    bucket = "your-terraform-state-bucket"
    key    = "open-transcribe/scaleway/terraform.tfstate"
    region = "fr-par"

    endpoints = { s3 = "https://s3.fr-par.scw.cloud" }

    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    use_lockfile                = true
  }
}
```

`get_repo_root()` shells out to `git rev-parse`, so it resolves only from inside the clone; use an explicit path if you keep the wrapper elsewhere. The `skip_*` arguments exist because Object Storage is S3-compatible rather than AWS. `use_lockfile = true` asks for Terraform 1.11's native S3 locking, which the module's `required_version` already allows; confirm it works against your bucket, because it depends on conditional writes rather than on Terraform, and serialize applies another way if the lock object cannot be created.

State is then remote, so the commands change shape but not order:

```bash
cd infra/live
terragrunt hcl fmt
terragrunt apply -target=scaleway_registry_namespace.this
terragrunt output -raw image_reference
terragrunt plan -out=open-transcribe.tfplan
terragrunt apply open-transcribe.tfplan
```

Two things move with the working directory. Terragrunt copies both the module and the wrapper directory's own files into `.terragrunt-cache/`, which is gitignored, so `terraform.tfvars` belongs next to the wrapper — or is passed through `inputs` in it — rather than in `infra/scaleway`; a saved plan file lands in that cache too, which is why the plan and the apply above have to run from the same wrapper directory. The image build in step 3 uses a relative context, so run `docker buildx build --platform linux/amd64 --push --tag "$IMAGE_REFERENCE" .` from the repository root instead of `../..` from the module.

## Updating the application

Use a new immutable tag for every build:

```bash
docker buildx build --platform linux/amd64 --push --tag "$REGISTRY_ENDPOINT/open-transcribe-mcp:1.0.0" ../..
```

Change `image_tag` to the same value, run `terraform plan`, then apply. For a tag that must be reused, pass its `sha256:...` registry digest as `image_digest`; Terraform uses it to force an exact redeployment.

## Operational checks

After deployment:

1. verify `/healthz` returns HTTP 200;
2. verify `/readyz` returns HTTP 200 and lists the intended provider;
3. verify `/mcp` rejects a missing or invalid bearer token;
4. run a short, authorized test recording;
5. if S3 is enabled, retrieve and delete a stored transcript and confirm no object survives the lifecycle window;
6. review Serverless Container logs to confirm transcript text, signed URL queries, phrase hints, and credentials are absent.

The repository automates checks 1 to 5 as an opt-in end-to-end suite. It skips itself unless a deployment URL is supplied, and it calls a real provider, so it costs money and never runs in CI:

```bash
cd infra/scaleway
export OT_E2E_BEARER_TOKEN="..."   # the deployment's OT_SECURITY__BEARER_TOKEN
uv run --directory ../.. pytest tests/e2e \
  --deployment-url "$(terraform output -raw mcp_endpoint)"
```

The URL is accepted in its base, `/mcp`, `/healthz`, or `/readyz` form, so any of the module's endpoint outputs works. By default the suite transcribes the repository's synthetic bilingual fixture, served from `raw.githubusercontent.com`, and compares the result to `tests/fixtures/reference-transcript.txt`. It asks the deployment which models are configured and requests only capabilities the selected model reports, so it works against any single configured provider; a Whisper deployment transcribes one language of that fixture and drops the other, which is why the comparison scores the best-matching speaker turn rather than the whole reference.

Point it at your own recording with `--audio-url` and `--expected-transcript` (a file path or literal text), pin the model with `--transcribe-provider` and `--transcribe-model`, and adjust `--min-word-coverage` (default `0.8`) and `--e2e-timeout` (default 600 seconds). Every option also reads an `OT_E2E_*` environment variable; prefer the variable for the token so it stays out of the shell history and process list. Transcript text is never printed, on success or on failure — only the reference words the deployment failed to return.

Add platform egress restrictions where available. Application SSRF checks complement, but do not replace, network-level blocking of metadata and private destinations.
