resource "scaleway_object_bucket" "results" {
  count = var.enable_result_store ? 1 : 0

  name          = local.result_bucket_name
  project_id    = var.project_id
  region        = var.region
  force_destroy = false
  tags = {
    application = "open-transcribe-mcp"
    managed-by  = "terraform"
  }

  lifecycle_rule {
    id      = "expire-temporary-transcripts"
    prefix  = "${local.result_prefix}/"
    enabled = true

    expiration {
      days = ceil(var.result_ttl_seconds / 86400)
    }
  }

  lifecycle_rule {
    id                                     = "abort-incomplete-uploads"
    enabled                                = true
    abort_incomplete_multipart_upload_days = 1
  }
}

resource "scaleway_object_bucket_acl" "results" {
  count = var.enable_result_store ? 1 : 0

  bucket     = scaleway_object_bucket.results[0].id
  acl        = "private"
  project_id = var.project_id
  region     = var.region
}

resource "scaleway_iam_application" "result_store" {
  count = var.enable_result_store ? 1 : 0

  name        = "${var.name_prefix}-result-store"
  description = "OpenTranscribe MCP temporary result store identity"
  tags        = local.resource_tags
}

resource "scaleway_iam_policy" "result_store" {
  count = var.enable_result_store ? 1 : 0

  name           = "${var.name_prefix}-result-store"
  description    = "Read, write, list, and delete temporary transcript objects"
  application_id = scaleway_iam_application.result_store[0].id
  tags           = local.resource_tags

  rule {
    project_ids = [var.project_id]
    permission_set_names = [
      "ObjectStorageBucketsRead",
      "ObjectStorageObjectsDelete",
      "ObjectStorageObjectsRead",
      "ObjectStorageObjectsWrite",
    ]
  }
}

resource "scaleway_iam_api_key" "result_store" {
  count = var.enable_result_store ? 1 : 0

  application_id     = scaleway_iam_application.result_store[0].id
  default_project_id = var.project_id
  description        = "Runtime credentials for OpenTranscribe MCP temporary results"

  depends_on = [scaleway_iam_policy.result_store]
}

resource "scaleway_object_bucket_policy" "results" {
  count = var.enable_result_store ? 1 : 0

  bucket     = scaleway_object_bucket.results[0].name
  project_id = var.project_id
  policy = jsonencode({
    Version = "2023-04-17"
    Id      = "OpenTranscribeResultStore"
    Statement = [
      {
        Sid       = "ListTranscriptPrefix"
        Effect    = "Allow"
        Principal = { SCW = "application_id:${scaleway_iam_application.result_store[0].id}" }
        Action    = ["s3:ListBucket"]
        Resource  = [scaleway_object_bucket.results[0].name]
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.result_prefix}/*"]
          }
        }
      },
      {
        Sid       = "ManageTranscriptObjects"
        Effect    = "Allow"
        Principal = { SCW = "application_id:${scaleway_iam_application.result_store[0].id}" }
        Action = [
          "s3:DeleteObject",
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = ["${scaleway_object_bucket.results[0].name}/${local.result_prefix}/*"]
      },
    ]
  })
}
