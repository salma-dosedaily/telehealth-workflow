#!/usr/bin/env bash
# GCP setup for Zoom fast path (meeting.ended + poll for transcript).
# Creates: Cloud Tasks queue, POLL_SECRET in GSM, enables APIs.
# You must add Zoom S2S OAuth secrets to GSM and redeploy the Zoom webhook with fast-path env.
#
# Prereqs: gcloud auth login, gcloud config set project dosedaily-raw
# Usage: ./scripts/setup_gcp_fast_path.sh

set -e
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
REGION="${GCP_REGION:-us-central1}"
QUEUE_NAME="${TASKS_QUEUE:-telehealth-poll}"

echo "=== GCP Fast Path Setup (project=$PROJECT region=$REGION) ==="

# 1. Enable Cloud Tasks API
echo "Enabling Cloud Tasks API..."
gcloud services enable cloudtasks.googleapis.com --project="$PROJECT"

# 2. Create the Cloud Tasks queue (idempotent: ignore error if already exists)
echo "Creating Cloud Tasks queue: $QUEUE_NAME..."
if gcloud tasks queues describe "$QUEUE_NAME" --location="$REGION" --project="$PROJECT" &>/dev/null; then
  echo "Queue $QUEUE_NAME already exists."
else
  gcloud tasks queues create "$QUEUE_NAME" \
    --location="$REGION" \
    --project="$PROJECT"
  echo "Queue $QUEUE_NAME created."
fi

# 3. Create POLL_SECRET in Secret Manager (random value); tag with project_name per principal-data-engineer
echo "Creating POLL_SECRET in Secret Manager..."
POLL_SECRET_VALUE="${POLL_SECRET_VALUE:-$(openssl rand -hex 24)}"
if gcloud secrets describe POLL_SECRET --project="$PROJECT" &>/dev/null; then
  echo "Secret POLL_SECRET already exists; adding new version..."
  echo -n "$POLL_SECRET_VALUE" | gcloud secrets versions add POLL_SECRET --data-file=- --project="$PROJECT"
else
  echo -n "$POLL_SECRET_VALUE" | gcloud secrets create POLL_SECRET \
    --data-file=- \
    --replication-policy=automatic \
    --project="$PROJECT"
fi
# Tag with project_name (GSM labels)
gcloud secrets update POLL_SECRET --update-labels=project_name=telehealth-workflow --project="$PROJECT" 2>/dev/null || true
# Grant Gen2 Cloud Function (Cloud Run) default compute SA access to the secret
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding POLL_SECRET \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="$PROJECT" --quiet 2>/dev/null || true
echo "POLL_SECRET created/updated; ${COMPUTE_SA} granted secretAccessor."

# 4. Output next steps: Zoom OAuth secrets + get URL and update function
echo ""
echo "=== Next steps ==="
echo "1. Add Zoom Server-to-Server OAuth credentials to Secret Manager (if not already):"
echo "   ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET"
echo "   e.g. echo -n 'your_account_id' | gcloud secrets create ZOOM_ACCOUNT_ID --data-file=- --project=$PROJECT"
echo "   Then tag: gcloud secrets update ZOOM_ACCOUNT_ID --update-labels=project_name=telehealth-workflow --project=$PROJECT"
echo ""
echo "2. Deploy (or redeploy) the Zoom webhook so it gets POLL_SECRET and Zoom OAuth from GSM:"
echo "   ./scripts/deploy_zoom_webhook.sh"
echo ""
echo "3. After deploy, set TELEHEALTH_WEBHOOK_URL on the function (replace URL with the one from step 2 output):"
echo "   URL=\$(gcloud functions describe telehealth_webhook_handler --gen2 --region=$REGION --project=$PROJECT --format='value(serviceConfig.uri)')"
echo "   gcloud functions deploy telehealth_webhook_handler --gen2 --region=$REGION --project=$PROJECT --update-env-vars=TELEHEALTH_WEBHOOK_URL=\$URL"
echo ""
echo "4. Allow the Cloud Tasks caller to reach the webhook (either):"
echo "   - Cloud Run → telehealth-webhook-handler → Security → Allow public access (handler still validates X-Poll-Secret), or"
echo "   - Grant Cloud Run Invoker to the service account that runs the Tasks queue."
echo ""
