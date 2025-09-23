variable "project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "Default region for regional resources"
  type        = string
  default     = "europe-west4"
}

variable "bucket_name" {
  description = "Globally-unique name for the data bucket (GCS)"
  type        = string
}

variable "cloud_run_service_name" {
  description = "Cloud Run service name"
  type        = string
  default     = "gantich-bot"
}

variable "app_image" {
  description = "Initial container image for Cloud Run service (CI/CD will update image on deploy)"
  type        = string
  default     = "europe-west4-docker.pkg.dev/filmtherapy-chat-bot/bot-images/interair/filmtherapy_chat_bot:main"
}

variable "github_owner" {
  description = "GitHub organization or user that owns the repository used for CI/CD"
  type        = string
  default     = null
}

variable "github_repo" {
  description = "GitHub repository name used for CI/CD"
  type        = string
  default     = null
}

variable "enable_wif" {
  description = "Whether to create Workload Identity Federation for GitHub OIDC"
  type        = bool
  default     = true
}

# Existing Secret Manager secret IDs (pre-created in Google)
variable "telegram_token_secret_id" {
  description = "Secret Manager secret ID for the Telegram bot token (e.g., TELEGRAM_TOKEN)"
  type        = string
  default     = "TELEGRAM_TOKEN"
}

variable "telegram_webhook_secret_id" {
  description = "Secret Manager secret ID for the Telegram webhook secret (e.g., TELEGRAM_WEBHOOK_SECRET)"
  type        = string
  default     = "TELEGRAM_WEBHOOK_SECRET"
}

variable "web_username_secret_id" {
  description = "Secret Manager secret ID for the web admin username (e.g., WEB_USERNAME)"
  type        = string
  default     = "WEB_USERNAME"
}

variable "web_password_secret_id" {
  description = "Secret Manager secret ID for the web admin password (e.g., WEB_PASSWORD)"
  type        = string
  default     = "WEB_PASSWORD"
}
