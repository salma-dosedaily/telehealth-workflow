#!/bin/bash
# Script to redeploy Calendly webhook with prefilled form configuration
# 
# INSTRUCTIONS:
# 1. Get your Google Form's pre-filled link (see steps above)
# 2. Replace the values below with your actual form details
# 3. Run this script: bash PREFILL_FORM_SETUP.sh

set -e

# ========== REPLACE THESE VALUES ==========
# Your Google Form base URL (everything before the ?)
export PREFILL_FORM_BASE_URL="https://docs.google.com/forms/d/e/YOUR_ACTUAL_FORM_ID/viewform"

# Entry ID for Patient Email field (the number after entry. in the prefilled URL)
export PREFILL_FORM_ENTRY_EMAIL="YOUR_EMAIL_ENTRY_ID"

# Entry ID for Patient Name field (optional, but recommended)
export PREFILL_FORM_ENTRY_NAME="YOUR_NAME_ENTRY_ID"
# ==========================================

export GCP_PROJECT=dosedaily-raw
export GCP_REGION=us-central1
export FIRESTORE_DATABASE_ID=telemeetinglog

echo "Deploying Calendly webhook with prefilled form configuration..."
echo "Base URL: $PREFILL_FORM_BASE_URL"
echo "Email Entry ID: $PREFILL_FORM_ENTRY_EMAIL"
echo "Name Entry ID: $PREFILL_FORM_ENTRY_NAME"
echo ""

bash scripts/deploy_calendly_webhook.sh

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Now when someone books via Calendly:"
echo "1. The system creates a prefilled form URL with their email and name"
echo "2. Stores it in Firestore"
echo "3. Kim gets the link via Slack reminder (15 min before call)"
echo ""
echo "Kim only needs to fill in:"
echo "- Her notes (with bullet points!)"
echo "- Meeting UUID (paste Zoom link)"
echo "- Product (if not auto-detected)"
