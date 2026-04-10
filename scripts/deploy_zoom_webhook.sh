#!/usr/bin/env bash
# Deploy main.py to the Zoom telehealth Cloud Function (Gen2).
# URL after deploy: https://zoom-telehealth-automation-<PROJECT_NUMBER>.us-central1.run.app
#
# Prereqs: gcloud auth login, gcloud config set project dosedaily-raw
# Optional: Add --set-secrets=...,GEMINI_API_KEY=GEMINI_API_KEY:latest for AI
# Uses --no-allow-unauthenticated to avoid org-policy 400; enable "Allow public access" in Cloud Run → Security if needed.

set -e
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
REGION="${GCP_REGION:-us-central1}"

echo "Deploying Zoom telehealth webhook to project=$PROJECT region=$REGION ..."

# Fast path: run ./scripts/setup_gcp_fast_path.sh first to create queue + POLL_SECRET. Add ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET to GSM.
SECRETS="ZOOM_SECRET_TOKEN=ZOOM_SECRET_TOKEN:latest,RUDDERSTACK_URL=RUDDERSTACK_URL:latest,RUDDERSTACK_WRITE_KEY=RUDDERSTACK_WRITE_KEY:latest"
for s in POLL_SECRET FORM_SUBMIT_SECRET ZOOM_ACCOUNT_ID ZOOM_CLIENT_ID ZOOM_CLIENT_SECRET ZOOM_REFRESH_TOKEN; do
  if gcloud secrets describe "$s" --project="$PROJECT" &>/dev/null; then
    SECRETS="$SECRETS,$s=$s:latest"
  fi
done
ENV_VARS="GCP_PROJECT=$PROJECT,GCP_REGION=$REGION,TASKS_QUEUE=telehealth-poll"
if [ -n "${FIRESTORE_DATABASE_ID:-}" ]; then
  ENV_VARS="$ENV_VARS,FIRESTORE_DATABASE_ID=$FIRESTORE_DATABASE_ID"
fi
gcloud functions deploy telehealth_webhook_handler \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=. \
  --entry-point=telehealth_webhook_handler \
  --trigger-http \
  --no-allow-unauthenticated \
  --set-secrets="$SECRETS" \
  --set-env-vars="$ENV_VARS" \
  --project="$PROJECT"

echo "Done. Get URL: gcloud functions describe telehealth_webhook_handler --gen2 --region=$REGION --project=$PROJECT --format='value(serviceConfig.uri)'"
echo "If Zoom gets 403: Cloud Run → telehealth-webhook-handler → Security → Allow public access"
echo "If you use a named Firestore DB (e.g. telemeetinglog): FIRESTORE_DATABASE_ID=telemeetinglog ./scripts/deploy_zoom_webhook.sh"
echo "Fast path: run ./scripts/setup_gcp_fast_path.sh once. Then set TELEHEALTH_WEBHOOK_URL (same as above) and allow public access so Tasks can POST."
