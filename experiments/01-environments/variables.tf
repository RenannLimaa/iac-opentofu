variable "env_name" {
  type        = string
  description = "Prefix used to isolate benchmark resources."
  default     = "bench"
}

variable "environment_type" {
  type        = string
  description = "Environment archetype: minimal, two-tier, multi-worker."
  default     = "minimal"

  validation {
    condition     = contains(["minimal", "two-tier", "multi-worker"], var.environment_type)
    error_message = "environment_type must be one of: minimal, two-tier, multi-worker."
  }
}

variable "worker_count" {
  type        = number
  description = "Number of workers used by the multi-worker archetype."
  default     = 8
}

variable "gateway_port" {
  type        = number
  description = "Host port used by the two-tier gateway."
  default     = 18080
}

variable "ingress_port" {
  type        = number
  description = "Host port used by the multi-worker ingress."
  default     = 19080
}
