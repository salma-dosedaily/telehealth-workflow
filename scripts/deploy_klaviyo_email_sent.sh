#!/usr/bin/env bash
# Deploy Klaviyo "email sent" callback: receives POST from Klaviyo flow webhook, posts to Slack.
#
# Slack: prefers Secret SLACK_WEBHOOK_URL_TELEHEALTH (same as Calendly reminder); else env SLACK_WEBHOOK_URL.
# Optional: KLAVIYO_CALLBACK_SECRET.
# In Klaviyo: add Webhook action after "Send Email" in the post-call flow; URL = this function's URL.
# See docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md Part 7.

set -e
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
REGION="${GCP_REGION:-us-central1}"

echo "Deploying Klaviyo email-sent callback from functions/klaviyo_email_sent (project=$PROJECT region=$REGION) ..."

ENV_VARS="GCP_PROJECT=$PROJECT"
[ -n "${KLAVIYO_CALLBACK_SECRET:-}" ] && ENV_VARS="$ENV_VARS,KLAVIYO_CALLBACK_SECRET=$KLAVIYO_CALLBACK_SECRET"

SECRET_ARGS=()
if gcloud secrets describe SLACK_WEBHOOK_URL_TELEHEALTH --project="$PROJECT" &>/dev/null; then
  SECRET_ARGS=(--set-secrets="SLACK_WEBHOOK_URL=SLACK_WEBHOOK_URL_TELEHEALTH:latest")
  echo "Using Secret Manager: SLACK_WEBHOOK_URL_TELEHEALTH"
elif [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
  ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
  echo "Using env SLACK_WEBHOOK_URL"
else
  echo "ERROR: No Slack URL. Run scripts/setup_slack_webhook_telehealth_secret.sh or export SLACK_WEBHOOK_URL="
  exit 1
fi

# Klaviyo must POST to this URL. Default: public invoke (--allow-unauthenticated).
# If deploy fails with "organization policy" / "permitted customer", either ask an org admin
# to allow unauthenticated invoke for this service, or deploy without public IAM and fix IAM later:
#   KLAVIYO_DEPLOY_NO_PUBLIC_IAM=1 ./scripts/deploy_klaviyo_email_sent.sh
AUTH_ARGS=(--allow-unauthenticated)
if [ "${KLAVIYO_DEPLOY_NO_PUBLIC_IAM:-}" = "1" ]; then
  AUTH_ARGS=(--no-allow-unauthenticated)
  echo "WARN: Deploying with --no-allow-unauthenticated (org policy workaround)."
  echo "     Klaviyo flow webhooks cannot reach this URL until run.invoker is granted (e.g. allUsers in Console if policy allows)."
fi

gcloud functions deploy klaviyo_email_sent_handler \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=functions/klaviyo_email_sent \
  --entry-point=klaviyo_email_sent_handler \
  --trigger-http \
  "${AUTH_ARGS[@]}" \
  --set-env-vars="$ENV_VARS" \
  "${SECRET_ARGS[@]}" \
  --project="$PROJECT"

URL=$(gcloud functions describe klaviyo_email_sent_handler --gen2 --region="$REGION" --project="$PROJECT" --format='value(serviceConfig.uri)' 2>/dev/null || true)
echo "Done. Callback URL: $URL"
echo "In Klaviyo: Flow → add Webhook after Send Email → URL = $URL. See docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md Part 7."
