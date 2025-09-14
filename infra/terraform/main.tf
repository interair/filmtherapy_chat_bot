data "google_project" "current" {}

# Enable required services
resource "google_project_service" "run" {
  project = var.project_id
  service = "run.googleapis.com"
}

resource "google_project_service" "storage" {
  project = var.project_id
  service = "storage.googleapis.com"
}

resource "google_project_service" "iamcredentials" {
  project = var.project_id
  service = "iamcredentials.googleapis.com"
}

# Enable Artifact Registry
resource "google_project_service" "artifactregistry" {
  project = var.project_id
  service = "artifactregistry.googleapis.com"
}

# Docker repository for container images
resource "google_artifact_registry_repository" "bot_images" {
  project       = var.project_id
  location      = var.region
  repository_id = "bot-images"
  format        = "DOCKER"
  description   = "Images for Cloud Run deployments"
}

# CI deployer can push to AR
resource "google_project_iam_member" "deployer_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Cloud Run runtime SA can pull from AR
resource "google_project_iam_member" "runtime_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Data bucket for persistent /app/src/data
resource "google_storage_bucket" "data" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 365
    }
  }

  depends_on = [
    google_project_service.storage
  ]
}

# Service account used by Cloud Run at runtime
resource "google_service_account" "runtime" {
  account_id   = "cloud-run-runtime"
  display_name = "Cloud Run runtime service account"
}

# Service account used by CI/CD to deploy
resource "google_service_account" "deployer" {
  account_id   = "cicd-deployer"
  display_name = "CI/CD deployer service account (GitHub Actions)"
}

# Grant runtime SA access to the bucket (for GCS Fuse)
resource "google_storage_bucket_iam_member" "runtime_bucket_rw" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

# Allow deployer to manage Cloud Run and act as runtime SA
resource "google_project_iam_member" "deployer_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_act_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# Optional Workload Identity Federation for GitHub OIDC
resource "google_iam_workload_identity_pool" "github" {
  count        = var.enable_wif ? 1 : 0
  project      = var.project_id
  display_name = "GitHub OIDC Pool"
  workload_identity_pool_id = "github-pool"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count       = var.enable_wif ? 1 : 0
  project     = var.project_id
  workload_identity_pool_id = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  display_name = "GitHub Provider"
  workload_identity_pool_provider_id = "github-provider"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_mapping = {
    "google.subject"           = "assertion.sub"
    "attribute.repository"     = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
  }

  # Restrict which identities can use this provider (must reference mapped attributes)
  attribute_condition = "attribute.repository == \"${var.github_owner}/${var.github_repo}\""
}

# Allow the specific GitHub repo to impersonate the deployer SA via WIF
resource "google_service_account_iam_member" "wif_impersonation" {
  count              = var.enable_wif && var.github_owner != null && var.github_repo != null ? 1 : 0
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_owner}/${var.github_repo}"
}

# Existing resources above...




# Cloud Run v2 service managed by Terraform
resource "google_cloud_run_v2_service" "app" {
  name     = var.cloud_run_service_name
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.runtime.email
    
    # Set to 1 for single-threaded bot with < 1 CPU
    max_instance_request_concurrency = 1

    containers {
      image = var.app_image

      env {
        name  = "WEB_PORT"
        value = "8080"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "USE_WEBHOOK"
        value = "true"
      }

      env {
        name  = "BASE_URL"
        value = "https://gantich-bot-1060292501119.europe-west4.run.app"
      }


      volume_mounts {
        name       = "data-vol"
        mount_path = "/app/src/data"
      }

      resources {
        limits = {
          memory = "512Mi"
          cpu    = "1"    # Now allowed with concurrency = 1
        }
        cpu_idle = false     # Allow CPU to idle when not processing
      }

      # Optimize startup probe for faster cold starts
      startup_probe {
        tcp_socket {
          port = 8080
        }
        initial_delay_seconds = 5
        timeout_seconds = 3
        failure_threshold = 3
        period_seconds = 5
      }
    }

    volumes {
      name = "data-vol"
      gcs {
        bucket    = google_storage_bucket.data.name
        read_only = false
      }
    }

    scaling {
      max_instance_count = 1
      min_instance_count = 1  # Scale to zero when not needed
    }
    # Reduce timeout for faster scale-down
    timeout = "60s"
    
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
  }
  traffic {
    percent         = 100
    type            = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }

  ingress = "INGRESS_TRAFFIC_ALL"

  depends_on = [
    google_project_service.run,
    google_storage_bucket.data
  ]
}

# Allow unauthenticated invocations
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  location = google_cloud_run_v2_service.app.location
  project  = var.project_id
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Firestore enablement
resource "google_project_service" "firestore" {
  project = var.project_id
  service = "firestore.googleapis.com"
}

resource "google_project_service" "datastore" {
  project = var.project_id
  service = "datastore.googleapis.com"
}

# Create Firestore database in Native mode if not exists
resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on = [
    google_project_service.firestore,
    google_project_service.datastore
  ]
}

# Allow runtime to access Firestore
resource "google_project_iam_member" "runtime_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
  depends_on = [google_service_account.runtime]
}

