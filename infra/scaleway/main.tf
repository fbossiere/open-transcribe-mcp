locals {
  resource_tags = distinct(concat([
    "application=open-transcribe-mcp",
    "managed-by=terraform",
  ], var.tags))

  image_reference = "${scaleway_registry_namespace.this.endpoint}/${var.image_name}:${var.image_tag}"
  result_prefix   = trim(var.result_prefix, "/")
  result_bucket_name = coalesce(
    var.result_bucket_name,
    "${var.name_prefix}-results-${substr(replace(var.project_id, "-", ""), 0, 12)}",
  )

  runtime_environment = merge(
    var.environment_variables,
    {
      OT_ENVIRONMENT                     = "prod"
      OT_HOST                            = "0.0.0.0"
      OT_PORT                            = "8000"
      OT_REQUEST_TIMEOUT_SECONDS         = tostring(var.request_timeout_seconds)
      OT_SECURITY__AUTH_MODE             = "bearer"
      OT_SECURITY__REQUIRE_HTTPS_SOURCES = "true"
      OT_SECURITY__ALLOW_PRIVATE_URLS    = "false"
    },
    var.enable_result_store ? {
      OT_RESULT_STORE__BACKEND         = "s3"
      OT_RESULT_STORE__TTL_SECONDS     = tostring(var.result_ttl_seconds)
      OT_RESULT_STORE__S3_BUCKET       = scaleway_object_bucket.results[0].name
      OT_RESULT_STORE__S3_ENDPOINT_URL = "https://s3.${var.region}.scw.cloud"
      OT_RESULT_STORE__S3_REGION       = var.region
      OT_RESULT_STORE__S3_PREFIX       = local.result_prefix
      } : {
      OT_RESULT_STORE__BACKEND = "disabled"
    },
  )

  runtime_secrets = merge(
    var.secret_environment_variables,
    var.enable_result_store ? {
      AWS_ACCESS_KEY_ID     = scaleway_iam_api_key.result_store[0].access_key
      AWS_SECRET_ACCESS_KEY = scaleway_iam_api_key.result_store[0].secret_key
    } : {},
  )
}

resource "scaleway_registry_namespace" "this" {
  name        = "${var.name_prefix}-registry"
  description = "Private images for OpenTranscribe MCP"
  is_public   = false
  project_id  = var.project_id
  region      = var.region
}

resource "scaleway_container_namespace" "this" {
  name        = "${var.name_prefix}-serverless"
  description = "OpenTranscribe MCP Serverless Containers namespace"
  project_id  = var.project_id
  region      = var.region
  tags        = local.resource_tags
}

resource "scaleway_container" "this" {
  name            = "${var.name_prefix}-mcp"
  description     = "Provider-independent speech-to-text MCP server"
  namespace_id    = scaleway_container_namespace.this.id
  image           = local.image_reference
  registry_sha256 = coalesce(var.image_digest, var.image_tag)

  port                      = 8000
  protocol                  = "http1"
  privacy                   = "public"
  https_connections_only    = true
  sandbox                   = "v2"
  cpu_limit                 = var.cpu_limit
  memory_limit_bytes        = var.memory_limit_bytes
  local_storage_limit_bytes = var.local_storage_limit_bytes
  min_scale                 = var.min_scale
  max_scale                 = var.max_scale
  timeout                   = var.request_timeout_seconds
  tags                      = local.resource_tags

  scaling_option {
    concurrent_requests_threshold = var.concurrent_requests_threshold
  }

  startup_probe {
    http {
      path = "/healthz"
    }
    failure_threshold = 12
    interval          = "5s"
    timeout           = "3s"
  }

  liveness_probe {
    http {
      path = "/healthz"
    }
    failure_threshold = 3
    interval          = "30s"
    timeout           = "5s"
  }

  environment_variables        = local.runtime_environment
  secret_environment_variables = local.runtime_secrets

  lifecycle {
    precondition {
      condition     = var.min_scale <= var.max_scale
      error_message = "min_scale cannot exceed max_scale."
    }

    precondition {
      condition     = !var.enable_result_store || trimspace(try(var.secret_environment_variables["OT_RESULT_STORE__CURSOR_SECRET"], "")) != ""
      error_message = "OT_RESULT_STORE__CURSOR_SECRET is required when enable_result_store is true."
    }

    precondition {
      condition     = trimspace(try(var.secret_environment_variables["OT_MICROSOFT__API_KEY"], "")) == "" || trimspace(try(var.environment_variables["OT_MICROSOFT__ENDPOINT"], "")) != ""
      error_message = "OT_MICROSOFT__ENDPOINT is required in environment_variables when OT_MICROSOFT__API_KEY is configured."
    }
  }

  depends_on = [
    scaleway_iam_policy.result_store,
    scaleway_object_bucket_acl.results,
    scaleway_object_bucket_policy.results,
  ]
}
