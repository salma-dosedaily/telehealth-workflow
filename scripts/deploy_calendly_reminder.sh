#!/usr/bin/env bash
# Deploy Calendly 15-min Slack reminder Cloud Function.
# Then set up Cloud Scheduler to POST every 5 min: scripts/setup_calendly_reminder_scheduler.sh
#
# Slack URL source (first match wins):
#   1) Secret SLACK_WEBHOOK_URL_TELEHEALTH — recommended so GSM secret SLACK_WEBHOOK_URL stays for ETL/other bots.
#   2) Env SLACK_WEBHOOK_URL — legacy; avoid sharing the same GSM secret name with ETL.
#
# Prereqs: FIRESTORE_DATABASE_ID (same as Calendly). Run scripts/setup_slack_webhook_telehealth_secret.sh once.

set -e
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
REGION="${GCP_REGION:-us-central1}"

echo "Deploying Calendly reminder from functions/calendly_reminder (project=$PROJECT region=$REGION) ..."

ENV_VARS="GCP_PROJECT=$PROJECT"
[ -n "${FIRESTORE_DATABASE_ID:-}" ] && ENV_VARS="$ENV_VARS,FIRESTORE_DATABASE_ID=$FIRESTORE_DATABASE_ID"
[ -n "${REMINDER_SECRET:-}" ] && ENV_VARS="$ENV_VARS,REMINDER_SECRET=$REMINDER_SECRET"

SECRET_ARGS=()
if gcloud secrets describe SLACK_WEBHOOK_URL_TELEHEALTH --project="$PROJECT" &>/dev/null; then
  SECRET_ARGS=(--set-secrets="SLACK_WEBHOOK_URL=SLACK_WEBHOOK_URL_TELEHEALTH:latest")
  echo "Using Secret Manager: SLACK_WEBHOOK_URL_TELEHEALTH → env SLACK_WEBHOOK_URL (telehealth-only; ETL can keep SLACK_WEBHOOK_URL)"
elif [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
  ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
  echo "Using env SLACK_WEBHOOK_URL (set SLACK_WEBHOOK_URL_TELEHEALTH in GSM to avoid clashing with ETL)"
else
  echo "ERROR: No Slack URL. Create secret SLACK_WEBHOOK_URL_TELEHEALTH (see scripts/setup_slack_webhook_telehealth_secret.sh) or export SLACK_WEBHOOK_URL="
  exit 1
fi

gcloud functions deploy calendly_reminder_handler \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=functions/calendly_reminder \
  --entry-point=calendly_reminder_handler \
  --trigger-http \
  --no-allow-unauthenticated \
  --set-env-vars="$ENV_VARS" \
  "${SECRET_ARGS[@]}" \
  --project="$PROJECT"

echo "Done. Get URL: gcloud functions describe calendly_reminder_handler --gen2 --region=$REGION --project=$PROJECT --format='value(serviceConfig.uri)'"
echo "Then run: FIRESTORE_DATABASE_ID=telemeetinglog REMINDER_SECRET=xxx ./scripts/setup_calendly_reminder_scheduler.sh"
