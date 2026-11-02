variable "image_tag" {
  description = "Git SHA of images already pushed to ECR. Pass the currently deployed tag on every apply: the deploy workflow owns later revisions."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.image_tag))
    error_message = "image_tag must be a full 40-character Git commit SHA."
  }
}

variable "app_password_version" {
  description = "Increase to generate and store a new clinic_app password; then run the deploy workflow so migrations apply it."
  type        = number
  default     = 1
}

variable "purge_schedule" {
  description = "EventBridge Scheduler expression (UTC) for the chat retention purge."
  type        = string
  default     = "cron(30 4 * * ? *)"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for task and database logs."
  type        = number
  default     = 7
}
