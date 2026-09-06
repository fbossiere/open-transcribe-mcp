variable "project_id" {
  description = "Scaleway Project ID that owns every resource. A dedicated project is recommended."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.project_id))
    error_message = "project_id must be a UUID."
  }
}

variable "region" {
  description = "Scaleway region for the registry, Serverless Container, and optional result bucket."
  type        = string
  default     = "fr-par"

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]{3}$", var.region))
    error_message = "region must use the Scaleway region form, for example fr-par."
  }
}

variable "name_prefix" {
  description = "Lowercase prefix used for resource names."
  type        = string
  default     = "open-transcribe"

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,47}[a-z0-9])?$", var.name_prefix))
    error_message = "name_prefix must contain 1-49 lowercase letters, digits, or internal hyphens."
  }
}

variable "image_name" {
  description = "Container image name inside the managed private registry namespace."
  type        = string
  default     = "open-transcribe-mcp"

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9._-]{0,126}[a-z0-9])?$", var.image_name))
    error_message = "image_name must be a valid lowercase container image name."
  }
}

variable "image_tag" {
  description = "Image tag to deploy. Use an immutable release or commit tag, never latest."
  type        = string
  default     = "0.1.0"

  validation {
    condition     = var.image_tag != "latest" && can(regex("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", var.image_tag))
    error_message = "image_tag must be a valid immutable image tag and cannot be latest."
  }
}

variable "image_digest" {
  description = "Optional sha256 image digest used to force an exact redeployment when a tag is reused."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.image_digest == null || can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be null or have the form sha256:<64 lowercase hex characters>."
  }
}

variable "environment_variables" {
  description = "Non-secret OT_* application overrides. Runtime and security invariants are set by the module."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for key in keys(var.environment_variables) :
      length(regexall("(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", upper(key))) == 0
    ])
    error_message = "Secret-looking values must be supplied through secret_environment_variables."
  }
}

variable "secret_environment_variables" {
  description = "Provider credentials and application secrets injected as Scaleway secret environment variables."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = alltrue([for value in values(var.secret_environment_variables) : trimspace(value) != ""])
    error_message = "secret_environment_variables cannot contain empty values."
  }

  validation {
    condition     = trimspace(try(var.secret_environment_variables["OT_SECURITY__BEARER_TOKEN"], "")) != ""
    error_message = "secret_environment_variables must contain a non-empty OT_SECURITY__BEARER_TOKEN."
  }

  validation {
    condition = anytrue([
      for key in [
        "OT_MICROSOFT__API_KEY",
        "OT_ELEVENLABS__API_KEY",
        "OT_GROQ__API_KEY",
      ] : trimspace(try(var.secret_environment_variables[key], "")) != ""
    ])
    error_message = "Configure at least one non-empty transcription provider API key."
  }
}

variable "min_scale" {
  description = "Minimum running instances. Zero enables scale-to-zero."
  type        = number
  default     = 0

  validation {
    condition     = var.min_scale >= 0 && var.min_scale <= 10 && floor(var.min_scale) == var.min_scale
    error_message = "min_scale must be an integer between 0 and 10."
  }
}

variable "max_scale" {
  description = "Maximum running instances."
  type        = number
  default     = 3

  validation {
    condition     = var.max_scale >= 1 && var.max_scale <= 20 && floor(var.max_scale) == var.max_scale
    error_message = "max_scale must be an integer between 1 and 20."
  }
}

variable "concurrent_requests_threshold" {
  description = "Concurrent requests per instance above which Scaleway scales out."
  type        = number
  default     = 4

  validation {
    condition     = var.concurrent_requests_threshold >= 1 && floor(var.concurrent_requests_threshold) == var.concurrent_requests_threshold
    error_message = "concurrent_requests_threshold must be a positive integer."
  }
}

variable "cpu_limit" {
  description = "CPU allocated to each instance, in Scaleway mvCPU units."
  type        = number
  default     = 500

  validation {
    condition     = var.cpu_limit >= 70 && floor(var.cpu_limit) == var.cpu_limit
    error_message = "cpu_limit must be an integer of at least 70 mvCPU."
  }
}

variable "memory_limit_bytes" {
  description = "Memory allocated to each instance in bytes. Defaults to 512 MiB."
  type        = number
  default     = 536870912

  validation {
    condition     = var.memory_limit_bytes >= 134217728 && floor(var.memory_limit_bytes) == var.memory_limit_bytes
    error_message = "memory_limit_bytes must be an integer of at least 128 MiB."
  }
}

variable "local_storage_limit_bytes" {
  description = "Ephemeral local storage per instance in bytes. Defaults to 1 GiB."
  type        = number
  default     = 1073741824

  validation {
    condition     = var.local_storage_limit_bytes >= 536870912 && floor(var.local_storage_limit_bytes) == var.local_storage_limit_bytes
    error_message = "local_storage_limit_bytes must be an integer of at least 512 MiB."
  }
}

variable "request_timeout_seconds" {
  description = "Maximum Serverless Container request duration."
  type        = number
  default     = 900

  validation {
    condition     = var.request_timeout_seconds >= 1 && var.request_timeout_seconds <= 900 && floor(var.request_timeout_seconds) == var.request_timeout_seconds
    error_message = "request_timeout_seconds must be an integer between 1 and 900."
  }
}

variable "enable_result_store" {
  description = "Create a private Object Storage result store, IAM identity, lifecycle, and runtime credentials."
  type        = bool
  default     = false
}

variable "result_bucket_name" {
  description = "Optional globally unique bucket name. A deterministic project-scoped name is used when null."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.result_bucket_name == null || can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.result_bucket_name))
    error_message = "result_bucket_name must be null or a valid 3-63 character S3 bucket name."
  }

  validation {
    condition = var.result_bucket_name == null || (
      !strcontains(var.result_bucket_name, "..") &&
      !strcontains(var.result_bucket_name, ".-") &&
      !strcontains(var.result_bucket_name, "-.") &&
      !can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$", var.result_bucket_name))
    )
    error_message = "result_bucket_name cannot use adjacent dots/dashes or an IPv4-address form."
  }
}

variable "result_prefix" {
  description = "Object key prefix dedicated to temporary transcripts."
  type        = string
  default     = "transcripts"

  validation {
    condition     = trim(var.result_prefix, "/") != "" && !strcontains(var.result_prefix, "..")
    error_message = "result_prefix must contain a non-empty safe prefix and cannot contain '..'."
  }
}

variable "result_ttl_seconds" {
  description = "Application result TTL. Bucket lifecycle rounds this up to full days."
  type        = number
  default     = 86400

  validation {
    condition     = var.result_ttl_seconds >= 60 && var.result_ttl_seconds <= 604800 && floor(var.result_ttl_seconds) == var.result_ttl_seconds
    error_message = "result_ttl_seconds must be an integer from 60 seconds through 7 days."
  }
}

variable "tags" {
  description = "Additional tags applied to resources that support them."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for tag in var.tags : trimspace(tag) != ""])
    error_message = "tags cannot contain empty values."
  }
}
