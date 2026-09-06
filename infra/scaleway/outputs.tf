output "registry_endpoint" {
  description = "Private registry endpoint used to tag and push the application image."
  value       = scaleway_registry_namespace.this.endpoint
}

output "image_reference" {
  description = "Full container image reference expected by the deployment."
  value       = local.image_reference
}

output "container_endpoint" {
  description = "HTTPS endpoint of the Serverless Container."
  value       = scaleway_container.this.public_endpoint
}

output "mcp_endpoint" {
  description = "Streamable HTTP MCP endpoint."
  value       = "${trimsuffix(scaleway_container.this.public_endpoint, "/")}/mcp"
}

output "health_endpoint" {
  description = "Unauthenticated liveness endpoint."
  value       = "${trimsuffix(scaleway_container.this.public_endpoint, "/")}/healthz"
}

output "result_bucket_name" {
  description = "Temporary transcript bucket name when the S3 result store is enabled."
  value       = var.enable_result_store ? scaleway_object_bucket.results[0].name : null
}
