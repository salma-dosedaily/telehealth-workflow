#!/usr/bin/env bash
# One-shot fix: separate Telehealth Slack from ETL so both do not share SLACK_WEBHOOK_URL in GSM.
#
# What it does:
#   1) Creates/updates Secret SLACK_WEBHOOK_URL_TELEHEALTH (telehealth Incoming Webhook only).
#   2) Optionally restores Secret SLACK_WEBHOOK_URL to your ETL webhook (so ETL stops posting to #telehealth-calls).
#   3) Redeploys calendly_reminder_handler and klaviyo_email_sent_handler to read Slack from the telehealth secret.
#
# Usage:
#   export GCP_PROJECT=dosedaily-raw GCP_REGION=us-central1 FIRESTORE_DATABASE_ID=telemeetinglog
#   export TELEHEALTH_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T.../B.../...'
#   export ETL_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T.../B.../...'   # required to fix ETL routing
#   ./scripts/apply_slack_webhook_separation_fix.sh
#
# Slack: create two Incoming Webhooks — one "Post to" telehealth channel, one "Post to" ETL/alerts channel.

set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"

echo "=== Slack webhook separation (Telehealth vs ETL) ==="
echo "Project: $PROJECT"
echo ""

if [ -z "${TELEHEALTH_SLACK_WEBHOOK_URL:-}" ]; then
  echo "ERROR: Export TELEHEALTH_SLACK_WEBHOOK_URL to the Incoming Webhook URL for your telehealth Slack channel."
  exit 1
fi

echo "[1/4] Telehealth secret SLACK_WEBHOOK_URL_TELEHEALTH ..."
TELEHEALTH_SLACK_WEBHOOK_URL="$TELEHEALTH_SLACK_WEBHOOK_URL" bash scripts/setup_slack_webhook_telehealth_secret.sh

if [ -n "${ETL_SLACK_WEBHOOK_URL:-}" ]; then
  echo ""
  echo "[2/4] Restore ETL secret SLACK_WEBHOOK_URL ..."
  ETL_SLACK_WEBHOOK_URL="$ETL_SLACK_WEBHOOK_URL" bash scripts/restore_etl_slack_webhook.sh
else
  echo ""
  echo "[2/4] SKIP restore SLACK_WEBHOOK_URL (ETL_SLACK_WEBHOOK_URL not set)."
  echo "      ETL will keep using the current SLACK_WEBHOOK_URL until you run:"
  echo "      ETL_SLACK_WEBHOOK_URL='https://hooks.slack.com/...' bash scripts/restore_etl_slack_webhook.sh"
fi

echo ""
echo "[3/4] Deploy calendly_reminder_handler ..."
export GCP_PROJECT="${GCP_PROJECT:-dosedaily-raw}"
export GCP_REGION="${GCP_REGION:-us-central1}"
export FIRESTORE_DATABASE_ID="${FIRESTORE_DATABASE_ID:-telemeetinglog}"
bash scripts/deploy_calendly_reminder.sh

echo ""
echo "[4/4] Deploy klaviyo_email_sent_handler ..."
if bash scripts/deploy_klaviyo_email_sent.sh; then
  echo "Klaviyo callback deploy OK."
else
  echo "WARN: klaviyo_email_sent deploy failed (often org IAM on allow-unauthenticated)."
  echo "      Redeploy from Cloud Console or fix org policy; use secret SLACK_WEBHOOK_URL_TELEHEALTH for SLACK_WEBHOOK_URL env."
fi

echo ""
echo "=== Done ==="
echo "Telehealth Cloud Functions use GSM: SLACK_WEBHOOK_URL_TELEHEALTH → runtime env SLACK_WEBHOOK_URL"
echo "ETL and other jobs should read GSM: SLACK_WEBHOOK_URL (ETL channel webhook only)."
echo "Details: docs/SLACK_WEBHOOK_SEPARATION.md"
