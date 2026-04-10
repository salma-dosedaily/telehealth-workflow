#!/usr/bin/env bash
# Create Cloud Scheduler job to trigger the Calendly reminder every 5 min.
# Run after deploy_calendly_reminder.sh. Requires: REMINDER_URL, REMINDER_SECRET (optional).
#
# Usage:
#   REMINDER_URL=$(gcloud functions describe calendly_reminder_handler --gen2 --region=us-central1 --project=dosedaily-raw --format='value(serviceConfig.uri)')
#   REMINDER_SECRET=your_random_secret
#   ./scripts/setup_calendly_reminder_scheduler.sh

set -e
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
REGION="${GCP_REGION:-us-central1}"

if [ -z "${REMINDER_URL:-}" ]; then
  echo "Getting reminder URL..."
  REMINDER_URL=$(gcloud functions describe calendly_reminder_handler --gen2 --region="$REGION" --project="$PROJECT" --format='value(serviceConfig.uri)' 2>/dev/null || true)
fi
if [ -z "${REMINDER_URL:-}" ]; then
  echo "ERROR: REMINDER_URL not set. Deploy the function first, then:"
  echo "  REMINDER_URL=\$(gcloud functions describe calendly_reminder_handler --gen2 --region=$REGION --project=$PROJECT --format='value(serviceConfig.uri)')"
  echo "  REMINDER_SECRET=xxx ./scripts/setup_calendly_reminder_scheduler.sh"
  exit 1
fi

# Cloud Scheduler needs to invoke the function. Optional REMINDER_SECRET sent as header for auth.
# Create uses --headers=KEY=VALUE; update uses --update-headers=KEY=VALUE (different flags).
HEADERS_CREATE=""
HEADERS_UPDATE=""
[ -n "${REMINDER_SECRET:-}" ] && HEADERS_CREATE="--headers=X-Reminder-Secret=$REMINDER_SECRET" && HEADERS_UPDATE="--update-headers=X-Reminder-Secret=$REMINDER_SECRET"

echo "Creating Cloud Scheduler job: calendly-reminder-every-5min"
if gcloud scheduler jobs describe calendly-reminder-every-5min --location="$REGION" --project="$PROJECT" &>/dev/null; then
  echo "Job exists. Updating..."
  gcloud scheduler jobs update http calendly-reminder-every-5min --location="$REGION" --schedule="*/5 * * * *" --uri="$REMINDER_URL" --http-method=POST $HEADERS_UPDATE --project="$PROJECT"
else
  gcloud scheduler jobs create http calendly-reminder-every-5min --location="$REGION" --schedule="*/5 * * * *" --uri="$REMINDER_URL" --http-method=POST $HEADERS_CREATE --project="$PROJECT"
fi
echo "Done. Job runs every 5 min. Grant Cloud Scheduler SA run.invoker on the function if you get 403."
echo "  gcloud run services add-iam-policy-binding calendly-reminder-handler --region=$REGION --member='serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com' --role='roles/run.invoker'"
echo "  (Or enable 'Allow unauthenticated' on the function for the scheduler to call it.)"
