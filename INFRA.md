# Infra (Terraform) — short notes

Minimal GCP infra to run on Cloud Run and persist small files via GCS.

Creates
- GCS bucket for data persistence
- Service accounts: runtime (for Cloud Run) and deployer (for CI)
- Optional WIF (Workload Identity Federation) for GitHub OIDC
- Required API enablement and IAM bindings

Folders
- infra/terraform: providers.tf, variables.tf, main.tf, outputs.tf

Quick start
1) cd infra/terraform
2) Create terraform.tfvars:
   project_id   = "your-project-id"
   region       = "europe-west4"
   bucket_name  = "your-unique-bucket"
   github_owner = "<owner>"
   github_repo  = "gantich-chat-bot-tg"
   enable_wif   = true
3) terraform init && terraform apply

After apply — add to GitHub repo variables
- GCP_PROJECT_ID, GCP_REGION
- SERVICE_ACCOUNT_EMAIL (deployer), WORKLOAD_IDENTITY_PROVIDER (if WIF)
- Optionally CLOUD_RUN_SERVICE, AR_REPOSITORY

Notes
- Runtime SA needs storage access if you mount the bucket with GCS Fuse in Cloud Run.
- Re-running terraform apply is safe; resources are idempotent.
- For key-based auth instead of WIF, create a JSON key for the deployer SA and save as GCP_SA_KEY secret.
