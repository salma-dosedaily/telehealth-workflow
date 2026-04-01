#!/bin/bash
# Deploy Calendly webhook with prefilled form configuration
# Extracted from: https://docs.google.com/forms/d/e/1FAIpQLSdWMAFl0ymLUjKJI963tVmpGfUiZBfM-bPxsr3CvuGLXvBi0A/viewform

set -e

# Extracted values from your Google Form
export PREFILL_FORM_BASE_URL="https://docs.google.com/forms/d/e/1FAIpQLSdWMAFl0ymLUjKJI963tVmpGfUiZBfM-bPxsr3CvuGLXvBi0A/viewform"
export PREFILL_FORM_ENTRY_EMAIL="1104708604"

# We need the Patient Name entry ID too - I'll show you how to get it below
export PREFILL_FORM_ENTRY_NAME=""

export GCP_PROJECT=dosedaily-raw
export GCP_REGION=us-central1
export FIRESTORE_DATABASE_ID=telemeetinglog

echo "=========================================="
echo "Deploying Calendly Webhook with Prefill"
echo "=========================================="
echo ""
echo "Form Base URL: $PREFILL_FORM_BASE_URL"
echo "Email Entry ID: $PREFILL_FORM_ENTRY_EMAIL"
echo "Name Entry ID: $PREFILL_FORM_ENTRY_NAME (will get later)"
echo ""

cd "$(dirname "$0")"
bash scripts/deploy_calendly_webhook.sh

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Next: Get the Patient Name entry ID"
echo "1. Go to your form → Get pre-filled link"
echo "2. Fill ONLY the Patient Name field (e.g., 'John Doe')"
echo "3. Click 'Get link'"
echo "4. Copy the URL and send it to me"
echo "5. I'll extract the name entry ID and redeploy"
echo ""
echo "For now, the form will prefill:"
echo "✅ Patient Email (working!)"
echo "⏳ Patient Name (need entry ID)"
