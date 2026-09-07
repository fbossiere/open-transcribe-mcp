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

- Terraform 1.11 or newer;
- Docker with BuildKit/buildx;
- a Scaleway Project, preferably dedicated to this deployment;
- a Scaleway API key allowed to create Container Registry, Serverless Containers, IAM, and optional Object Storage resources;
- at least one transcription-provider credential.

Export the Scaleway credentials for the provider. Do not put them in `terraform.tfvars`:

```bash
export SCW_ACCESS_KEY="SCW..."
export SCW_SECRET_KEY="..."
export SCW_DEFAULT_PROJECT_ID="00000000-0000-0000-0000-000000000000"
```

## 1. Configure Terraform

```bash
cd infra/scaleway
cp terraform.tfvars.example terraform.tfvars
```

Set the real `project_id`, an immutable `image_tag`, provider configuration, a strong MCP bearer token, and provider credentials. Generate secrets locally, for example:

```bash
openssl rand -hex 32
```

Never commit `terraform.tfvars`, Terraform state, credentials, live signed URLs, recordings, or transcripts.

## 2. Bootstrap the private registry

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

## 3. Apply the complete deployment

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

## Secrets and Terraform state

Scaleway Serverless Containers accepts secret environment variables, but its Terraform resource does not currently bind an environment variable to a Scaleway Secret Manager version. Terraform therefore receives the runtime secret values, and they can exist in state even though plans and CLI output redact them.

Use an encrypted remote state backend with tightly restricted access. Secret Manager resources alone would duplicate secrets without injecting them into the container or eliminating state exposure. Rotate the MCP token and provider keys if state is exposed.

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

Add platform egress restrictions where available. Application SSRF checks complement, but do not replace, network-level blocking of metadata and private destinations.
