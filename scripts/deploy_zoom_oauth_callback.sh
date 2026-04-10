#!/usr/bin/env bash
# Deploy the Zoom OAuth callback (HTTPS) so Zoom can redirect here.
# Zoom requires a secure (HTTPS) redirect URL; this provides it.
#
# After deploy:
# 1. Get the URL: gcloud functions describe zoom_oauth_callback --gen2 --region=us-central1 --project=dosedaily-raw --format='value(serviceConfig.uri)'
# 2. Add to Zoom General App redirect allow list: https://YOUR-URL/callback  (same base + /callback)
# 3. Open the URL in a browser (no /callback), click "Authorize Zoom", complete flow; token is saved to GSM.

set -e
cd "$(dirname "$0")/.."
PROJECT="${GCP_PROJECT:-dosedaily-raw}"
REGION="${GCP_REGION:-us-central1}"

echo "Deploying Zoom OAuth callback (HTTPS) to project=$PROJECT region=$REGION ..."

# Zoom app credentials: set env before running, or pass via --update-env-vars after first deploy
ENV_VARS="GCP_PROJECT=$PROJECT"
if [[ -n "$ZOOM_CLIENT_ID" && -n "$ZOOM_CLIENT_SECRET" ]]; then
  ENV_VARS="$ENV_VARS,ZOOM_CLIENT_ID=$ZOOM_CLIENT_ID,ZOOM_CLIENT_SECRET=$ZOOM_CLIENT_SECRET"
fi

# Use --no-allow-unauthenticated if your org policy blocks allUsers (you'll need to allow public access manually in Console for the OAuth redirect to work)
gcloud functions deploy zoom_oauth_callback \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=functions/zoom_oauth_callback \
  --entry-point=zoom_oauth_callback \
  --trigger-http \
  --no-allow-unauthenticated \
  --set-env-vars="$ENV_VARS" \
  --project="$PROJECT"

URL=$(gcloud functions describe zoom_oauth_callback --gen2 --region="$REGION" --project="$PROJECT" --format='value(serviceConfig.uri)' 2>/dev/null || true)
echo ""
echo "Done. Add this Redirect URL in Zoom General App (exactly):"
echo "  ${URL}/callback"
echo ""
echo "Then open in a browser (meeting host signs in and authorizes):"
echo "  $URL"
echo ""
echo "Set ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET when deploying (env or Secret Manager). If not set, set them and redeploy:"
echo "  cd $(pwd) && gcloud functions deploy zoom_oauth_callback --gen2 --region=$REGION --project=$PROJECT --source=functions/zoom_oauth_callback --update-env-vars=ZOOM_CLIENT_ID=xxx,ZOOM_CLIENT_SECRET=xxx"
echo ""
echo "If Zoom cannot reach the callback (403): Cloud Run -> zoom-oauth-callback -> Security -> Allow public access."
echo "If your org policy blocks public access, use the ngrok workaround: docs/ZOOM_FAST_PATH_SETUP.md (HTTPS redirect workaround)."
