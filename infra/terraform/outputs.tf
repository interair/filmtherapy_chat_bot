output "project_id" {
  value       = var.project_id
  description = "GCP project ID"
}

output "region" {
  value       = var.region
  description = "GCP region"
}

output "bucket" {
  value = {
    name     = google_storage_bucket.data.name
    location = google_storage_bucket.data.location
  }
  description = "Data bucket details"
}

output "service_accounts" {
  value = {
    runtime_email  = google_service_account.runtime.email
    deployer_email = google_service_account.deployer.email
  }
  description = "Service account emails"
}

output "wif" {
  value = var.enable_wif ? {
    pool_name     = try(google_iam_workload_identity_pool.github[0].name, null)
    provider_name = try(google_iam_workload_identity_pool_provider.github[0].name, null)
  } : null
  description = "Workload Identity Federation resource names"
}



