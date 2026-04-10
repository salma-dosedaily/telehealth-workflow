#!/usr/bin/env bash
# Deploy Calendly webhook Cloud Function from functions/calendly ONLY.
# Deploying from repo root can pull in main.py (Zoom code + genai) and crash the service.
#
# Prereqs: gcloud auth login, CALENDLY_PERSONAL_ACCESS_TOKEN secret in GSM

set -e
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
REGION="${GCP_REGION:-us-central1}"

echo "Deploying Calendly webhook from functions/calendly (project=$PROJECT region=$REGION) ..."

ENV_VARS="GCP_PROJECT=$PROJECT"
[ -n "${FIRESTORE_DATABASE_ID:-}" ] && ENV_VARS="$ENV_VARS,FIRESTORE_DATABASE_ID=$FIRESTORE_DATABASE_ID"
if [ -n "${PREFILL_FORM_BASE_URL:-}" ]; then
  ENV_VARS="$ENV_VARS,PREFILL_FORM_BASE_URL=$PREFILL_FORM_BASE_URL"
  [ -n "${PREFILL_FORM_ENTRY_EMAIL:-}" ] && ENV_VARS="$ENV_VARS,PREFILL_FORM_ENTRY_EMAIL=$PREFILL_FORM_ENTRY_EMAIL"
  [ -n "${PREFILL_FORM_ENTRY_NAME:-}" ] && ENV_VARS="$ENV_VARS,PREFILL_FORM_ENTRY_NAME=$PREFILL_FORM_ENTRY_NAME"
fi
# Email prefilled link to host (Kim) via SendGrid
[ -n "${SENDGRID_FROM_EMAIL:-}" ] && ENV_VARS="$ENV_VARS,SENDGRID_FROM_EMAIL=$SENDGRID_FROM_EMAIL"
[ -n "${HOST_EMAIL:-}" ] && ENV_VARS="$ENV_VARS,HOST_EMAIL=$HOST_EMAIL"

SECRETS="CALENDLY_PERSONAL_ACCESS_TOKEN=CALENDLY_PERSONAL_ACCESS_TOKEN:latest"
if [ -n "${SENDGRID_FROM_EMAIL:-}" ]; then
  SECRETS="$SECRETS,SENDGRID_API_KEY=SENDGRID_API_KEY:latest"
fi

# Deploy without --allow-unauthenticated to avoid org-policy error; enable public access in Console (Security tab) if needed
gcloud functions deploy calendly_webhook_handler \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=functions/calendly \
  --entry-point=calendly_webhook_handler \
  --trigger-http \
  --no-allow-unauthenticated \
  --set-secrets="$SECRETS" \
  --set-env-vars="$ENV_VARS" \
  --project="$PROJECT"

echo "Done. Get URL: gcloud functions describe calendly_webhook_handler --gen2 --region=$REGION --project=$PROJECT --format='value(serviceConfig.uri)'"
echo "Then register with Calendly (token from Secret Manager): python scripts/register_calendly_webhook.py --url <URL> --from-secret-manager"
echo "Optional prefill: set PREFILL_FORM_BASE_URL, PREFILL_FORM_ENTRY_EMAIL, PREFILL_FORM_ENTRY_NAME and redeploy."
echo "Optional email to Kim: set SENDGRID_FROM_EMAIL, HOST_EMAIL, create SENDGRID_API_KEY in GSM. See docs/CALENDLY_PREFILL_FORM.md"
