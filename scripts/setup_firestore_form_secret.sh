#!/usr/bin/env bash
# Enable Firestore and create FORM_SUBMIT_SECRET for Google Form → Cloud Function.
# Required when using the optional "Meeting UUID" form field so the function can:
# - Store meeting.ended in Firestore (host_email, meeting_date, duration)
# - Look up by meeting_uuid on form submit and add host_email/meeting_date to the event.
#
# Prereqs: gcloud auth login, gcloud config set project dosedaily-raw
# Usage: ./scripts/setup_firestore_form_secret.sh
# After running: redeploy telehealth_webhook_handler (./scripts/deploy_zoom_webhook.sh),
#                then set the same FORM_SUBMIT_SECRET value in the form Apps Script.

set -e
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
REGION="${GCP_REGION:-us-central1}"

echo "=== Firestore + FORM_SUBMIT_SECRET setup (project=$PROJECT) ==="

# 1. Enable Firestore API (required for meeting_uuid lookup when form is used)
echo "Enabling Firestore API..."
gcloud services enable firestore.googleapis.com --project="$PROJECT"

# 2. Create the default Firestore database if it does not exist (required; enabling API is not enough)
echo "Ensuring Firestore (default) database exists..."
if gcloud firestore databases create --location="$REGION" --project="$PROJECT" 2>/dev/null; then
  echo "Firestore database created."
else
  # Already exists, or list to confirm
  if gcloud firestore databases list --project="$PROJECT" 2>/dev/null | head -5 | grep -q .; then
    echo "Firestore database already exists (or create failed for another reason)."
  else
    echo "Create the Firestore database manually: https://console.cloud.google.com/datastore/setup?project=$PROJECT"
    echo "  Choose 'Firestore Native mode' and location $REGION, then re-run this script."
    exit 1
  fi
fi

# 3. Grant default compute SA (used by Cloud Function) permission to use Firestore
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "Granting Firestore (datastore.user) to ${COMPUTE_SA}..."
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role=roles/datastore.user \
  --quiet 2>/dev/null || true
echo "Firestore access granted."

# 4. Create FORM_SUBMIT_SECRET in Secret Manager (random value); tag with project_name
echo "Creating FORM_SUBMIT_SECRET in Secret Manager..."
if gcloud secrets describe FORM_SUBMIT_SECRET --project="$PROJECT" &>/dev/null; then
  if [ -n "${FORM_SUBMIT_SECRET_VALUE}" ]; then
    echo "Secret FORM_SUBMIT_SECRET already exists; adding new version..."
    echo -n "$FORM_SUBMIT_SECRET_VALUE" | gcloud secrets versions add FORM_SUBMIT_SECRET --data-file=- --project="$PROJECT"
    FORM_SECRET_VALUE="$FORM_SUBMIT_SECRET_VALUE"
  else
    echo "Secret FORM_SUBMIT_SECRET already exists. To rotate: FORM_SUBMIT_SECRET_VALUE=xxx ./scripts/setup_firestore_form_secret.sh"
    FORM_SECRET_VALUE=""
  fi
else
  FORM_SECRET_VALUE="${FORM_SUBMIT_SECRET_VALUE:-$(openssl rand -hex 24)}"
  echo -n "$FORM_SECRET_VALUE" | gcloud secrets create FORM_SUBMIT_SECRET \
    --data-file=- \
    --replication-policy=automatic \
    --project="$PROJECT"
fi
gcloud secrets update FORM_SUBMIT_SECRET --update-labels=project_name=telehealth-workflow --project="$PROJECT" 2>/dev/null || true
gcloud secrets add-iam-policy-binding FORM_SUBMIT_SECRET \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="$PROJECT" --quiet 2>/dev/null || true
echo "FORM_SUBMIT_SECRET ready; ${COMPUTE_SA} granted secretAccessor."

echo ""
echo "=== Next steps ==="
echo "1. Redeploy the webhook so it gets FORM_SUBMIT_SECRET from GSM:"
echo "   ./scripts/deploy_zoom_webhook.sh"
echo ""
echo "2. In Google Apps Script (Form → Script editor), set the SAME secret value:"
echo "   const FORM_SUBMIT_SECRET = \"<paste value below>\";"
if [ -n "$FORM_SECRET_VALUE" ]; then
  echo ""
  echo "   Value (save securely; not shown again): $FORM_SECRET_VALUE"
fi
echo ""
echo "3. In the Google Form, add a short-answer optional field titled \"Meeting UUID\""
echo "   so Kim can paste the Zoom meeting UUID to tie the form to the meeting and"
echo "   get host_email / meeting_date in the RudderStack event."
echo ""
