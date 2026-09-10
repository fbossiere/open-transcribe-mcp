# Scaleway Terraform

This root module deploys OpenTranscribe MCP on Scaleway Serverless Containers. It creates:

- a private Container Registry namespace;
- a Serverless Containers namespace;
- one public-HTTPS Serverless Container protected by OpenTranscribe bearer authentication;
- optional private Object Storage, lifecycle deletion, and a dedicated IAM application for stored results.

The registry must contain the selected image before the final apply. See
[`../../docs/deploy-scaleway.md`](../../docs/deploy-scaleway.md) for the bootstrap and deployment sequence.

## Deployment credentials

Terraform authenticates as a Scaleway IAM application through `SCW_ACCESS_KEY` and `SCW_SECRET_KEY`. The key needs `ContainerRegistryFullAccess` and `ContainersFullAccess` scoped to the deployment project, plus `ObjectStorageFullAccess` on that project and organization-scoped `IAMManager` when `enable_result_store = true`. `IAMManager` cannot be narrowed to a project and grants organization-wide escalation, so keep it on a separate bootstrap key rather than the key used for routine deployments. [`../../docs/deploy-scaleway.md`](../../docs/deploy-scaleway.md) has the console and CLI procedures and the bucket-policy caveat that applies once the result store exists.

## Inputs that contain secrets

`secret_environment_variables` is marked sensitive and is sent to Scaleway as secret container environment variables. The Scaleway provider still has to receive these values, so Terraform state can contain them. Use encrypted remote state with tightly scoped access, never commit state, and rotate secrets after any suspected state exposure.

Scaleway Secret Manager is not created here because Serverless Containers do not currently expose a native Terraform reference from a container environment variable to a Secret Manager version. Creating duplicate Secret Manager objects would not remove the state exposure or inject them into the workload.

The module rejects empty secrets, requires MCP bearer authentication, and requires at least one configured provider key. This prevents successful infrastructure deployment followed by a container crash caused by empty values.

## Result-store isolation

`enable_result_store = true` creates a private bucket and an IAM application whose bucket policy is restricted to the configured transcript prefix. IAM permission sets are project-scoped, so a dedicated Scaleway Project is recommended to make the runtime identity's effective boundary match the deployment boundary.

The bucket refuses Terraform destruction while it still contains objects. Its lifecycle removes transcript objects after the configured TTL rounded up to full days; the application independently enforces the exact TTL from object metadata.
