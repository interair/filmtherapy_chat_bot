# Deploy to Google Cloud Run (short guide)

We deploy from GitHub Actions using .github/workflows/cloud-run-deploy.yml. It builds the image and pushes to Google Artifact Registry, then deploys to Cloud Run and sets the Telegram webhook (if BASE_URL and TELEGRAM_TOKEN are set).

## Requirements
- GCP project. Required APIs (Cloud Run, Artifact Registry, IAM Credentials, Cloud Storage) are enabled automatically by Terraform in infra/terraform. 
- Service Account for deploy (WIF preferred) and optional runtime SA for Cloud Run.

## Repository variables/secrets
Set in GitHub → Settings → Secrets and variables → Actions

Variables
- GCP_PROJECT_ID (e.g., my-gcp-project)
- GCP_REGION (e.g., europe-west4)
- CLOUD_RUN_SERVICE (e.g., app-service)
- WORKLOAD_IDENTITY_PROVIDER (WIF provider resource name)
- SERVICE_ACCOUNT_EMAIL (SA used with WIF)
- AR_REPOSITORY (Artifact Registry repo, default bot-images)
- Optional app config used at deploy: ADMINS, BASE_URL, USE_WEBHOOK

Secrets
- GCP_SA_KEY (only if not using WIF)
- TELEGRAM_TOKEN, WEB_USERNAME, WEB_PASSWORD (app secrets)

## How it works
- Auth via WIF if configured, otherwise via GCP_SA_KEY.
- docker/build-push-action builds and pushes image to REGION-docker.pkg.dev/PROJECT/AR_REPOSITORY/owner/repo:ref
- gcloud run deploy uses that image and passes minimal env vars (from repo vars/secrets) as an env file.
- After deploy, the workflow calls Telegram setWebhook if TELEGRAM_TOKEN and BASE_URL are present.

## First setup
1) Create an Artifact Registry repo (e.g., bot-images) in your region.
2) Ensure a GCS bucket exists if you plan to persist /app/src/data via GCS Fuse (see infra notes).
3) Grant deploy SA: roles/run.admin and roles/iam.serviceAccountUser. Grant runtime SA access to any buckets it needs.
4) Fill variables/secrets as above. Push to main or trigger the workflow manually.

Troubleshooting
- Check Actions logs for auth/image/deploy errors.
- Verify BASE_URL is public and ends with your domain; webhook is set to BASE_URL/tg/webhook.
- Ensure required variables are set; the workflow fails fast if GCP_PROJECT_ID is missing.
