# Security Guidelines

Last updated: 2025-09-21

This document summarizes the security posture of the project and required practices for CI/CD and infrastructure.

## Reporting
- Do not open public GitHub issues for security topics.
- Report privately to the maintainers via our internal channels. Include impact, steps to reproduce, and commit/sha.

## Secrets Management
- Never commit real secrets. Local development may use a local .env file; production uses Google Secret Manager.
- Cloud Run is deployed with Secret Manager references (gcloud run deploy --set-secrets ...), so values are not exposed in the UI.
- GitHub Actions must NOT use long‑lived GCP JSON keys. Authentication uses GitHub OIDC Workload Identity Federation (WIF) only.
- The Telegram webhook step uses TELEGRAM_TOKEN from repository secrets. Keep it limited to that step only and rotate if leaked.

## Terraform State and IaC
- Terraform state MUST NOT be stored in the repository. The configuration uses a remote GCS backend.
  - Initialize/migrate: terraform init -migrate-state -backend-config="bucket=<your-state-bucket>" -backend-config="prefix=terraform/state"
- Do not commit terraform.tfstate, *.tfvars, or plan outputs. These are ignored by .gitignore.
- If state or tfvars were committed historically, treat them as leaked: rotate any secrets referenced and remove files from history if feasible.

## Cloud Resources
- GCS bucket for data storage has Public Access Prevention enforced and Uniform Bucket-Level Access enabled.
- Cloud Run service allows unauthenticated access (required for Telegram webhook) and uses a dedicated runtime service account with least privileges.
- Use strong WEB_USERNAME/WEB_PASSWORD if enabling the web admin; the service enforces constant‑time comparison to mitigate timing attacks.

## CI/CD Hardening
- The deployment workflow requires WIF variables (WORKLOAD_IDENTITY_PROVIDER, SERVICE_ACCOUNT_EMAIL) and fails if not set.
- Actions are version-pinned by major version; review and pin by commit SHA for additional supply chain hardening where feasible.

## Application
- Avoid logging sensitive data (tokens, credentials, PII). Logs are stored locally in logs/ for dev and should be rotated/limited in production.
- Keep dependencies up to date (requirements.txt). Use dependabot or scheduled reviews.
