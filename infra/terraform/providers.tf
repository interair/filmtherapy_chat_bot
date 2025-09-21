terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
  # Store Terraform state securely in Google Cloud Storage
  # Configure via: terraform init -backend-config="bucket=YOUR_BUCKET" -backend-config="prefix=terraform/state"
  # backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
