#!/usr/bin/env bash
# Create a DEDICATED Secret Manager secret for Telehealth Slack (Calendly reminder + Klaviyo callback).
# Keeps SLACK_WEBHOOK_URL free for ETL / other bots so updating telehealth does not reroute ETL into #telehealth-calls.
#
# Usage:
#   TELEHEALTH_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...' ./scripts/setup_slack_webhook_telehealth_secret.sh
#
# After this:
#   1. Restore SLACK_WEBHOOK_URL to your ETL bot webhook (see scripts/restore_etl_slack_webhook.sh or gcloud secrets versions add).
#   2. Redeploy: ./scripts/deploy_calendly_reminder.sh && ./scripts/deploy_klaviyo_email_sent.sh (scripts auto-use the telehealth secret).

set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
SECRET_ID="SLACK_WEBHOOK_URL_TELEHEALTH"
URL="${TELEHEALTH_SLACK_WEBHOOK_URL:-}"

if [ -z "$URL" ]; then
  echo "ERROR: Set TELEHEALTH_SLACK_WEBHOOK_URL to the Incoming Webhook URL for your telehealth Slack channel."
  echo "Example: TELEHEALTH_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T.../B.../...' $0"
  exit 1
fi

NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
SA="${NUM}-compute@developer.gserviceaccount.com"

if ! gcloud secrets describe "$SECRET_ID" --project="$PROJECT" &>/dev/null; then
  gcloud secrets create "$SECRET_ID" \
    --project="$PROJECT" \
    --replication-policy="automatic"
  echo "Created secret $SECRET_ID"
fi

echo -n "$URL" | gcloud secrets versions add "$SECRET_ID" \
  --project="$PROJECT" \
  --data-file=-

gcloud secrets add-iam-policy-binding "$SECRET_ID" \
  --project="$PROJECT" \
  --member="serviceAccount:${SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet

echo ""
echo "OK: $SECRET_ID updated. Default compute SA can read it."
echo ""
echo "NEXT — restore ETL (do not skip):"
echo "  Put your ETL bot webhook back on SLACK_WEBHOOK_URL so pipelines stop posting to telehealth:"
echo "  echo -n 'https://hooks.slack.com/services/...ETL...' | gcloud secrets versions add SLACK_WEBHOOK_URL --project=$PROJECT --data-file=-"
echo ""
echo "Then redeploy telehealth functions:"
echo "  export GCP_PROJECT=$PROJECT FIRESTORE_DATABASE_ID=telemeetinglog"
echo "  ./scripts/deploy_calendly_reminder.sh"
echo "  ./scripts/deploy_klaviyo_email_sent.sh"
