# Deploy on Scaleway Serverless Containers

Reference starting point: `fr-par`, minimum scale 0, maximum scale 3, 512 MB memory, 250–500 mCPU, concurrency 4, one application worker, and a 15-minute request timeout. Validate provider and platform duration limits for real recordings.

1. Build the `linux/amd64` Docker image and push it to a private Scaleway Container Registry namespace.
2. Create a Serverless Container from that image, expose port 8000, and set minimum scale to zero.
3. Store provider keys and the MCP bearer/cursor secrets in Scaleway Secret Manager, then inject them as the `OT_*` environment variables shown in `.env.example`.
4. Configure the platform health check as `GET /healthz`; use `/readyz` when readiness-aware routing is available.
5. Set the public request timeout to 900 seconds and limit concurrency to four initially.

For stored results, create a private Object Storage bucket with a one-day lifecycle deletion rule and install the `s3` extra in the image. Configure:

```dotenv
OT_RESULT_STORE__BACKEND=s3
OT_RESULT_STORE__CURSOR_SECRET=RANDOM-SHARED-SECRET
OT_RESULT_STORE__S3_BUCKET=open-transcribe-results
OT_RESULT_STORE__S3_ENDPOINT_URL=https://s3.fr-par.scw.cloud
OT_RESULT_STORE__S3_REGION=fr-par
```

Grant only list/get/put/delete permissions for the configured bucket/prefix. The bearer and cursor secrets must be identical across instances. Do not bake `.env` into the image.

Scale-to-zero is safe for inline and S3 modes. Do not use the memory store with multiple instances or when results must survive cold starts.

Add platform egress restrictions where possible. Application SSRF checks are not a substitute for blocking metadata and private networks at the network layer.
