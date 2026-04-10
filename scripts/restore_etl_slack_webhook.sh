#!/usr/bin/env bash
# Restore the shared secret SLACK_WEBHOOK_URL to your ETL / data pipeline Slack webhook.
# Use this after telehealth was moved to SLACK_WEBHOOK_URL_TELEHEALTH so ETL stops posting to #telehealth-calls.
#
# Usage:
#   ETL_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...' ./scripts/restore_etl_slack_webhook.sh

set -euo pipefail
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
URL="${ETL_SLACK_WEBHOOK_URL:-}"

if [ -z "$URL" ]; then
  echo "ERROR: Set ETL_SLACK_WEBHOOK_URL to the Incoming Webhook URL for your ETL / alerts channel."
  exit 1
fi

echo -n "$URL" | gcloud secrets versions add SLACK_WEBHOOK_URL \
  --project="$PROJECT" \
  --data-file=-

echo "OK: New version of SLACK_WEBHOOK_URL added. ETL jobs that read this secret will use it on next run."
