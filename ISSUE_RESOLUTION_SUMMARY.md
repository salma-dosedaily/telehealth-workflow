# Zoom Link & Firestore Storage Issue - Resolution Summary

**Date:** 2026-03-27  
**Issue:** Zoom links no longer sending Slack messages and not storing data in Firestore

---

## Root Causes Identified

### 1. Missing Environment Variables
Both Cloud Functions were deployed without critical environment variables:

**`calendly_webhook_handler`:**
- ❌ Missing: `FIRESTORE_DATABASE_ID` (was using default DB instead of `telemeetinglog`)
- ❌ Missing: Prefill form configuration (had placeholder values)
- ❌ Missing: SendGrid email configuration

**`calendly_reminder_handler`:**
- ❌ Missing: `FIRESTORE_DATABASE_ID`
- ❌ Missing: `SLACK_WEBHOOK_URL`

### 2. Firestore Data Issues
Checking the `calendly_prefilled_forms` collection revealed:
- **Some bookings have Zoom links** (e.g., shivangi@dosedaily.co bookings)
- **Many bookings missing Zoom links** (showing `N/A`)
- **Some bookings missing `event_start_utc`** (showing `None`)

This explains why Slack reminders weren't being sent - the code requires both `zoom_join_url` and `event_start_utc` to send reminders.

---

## Fixes Applied

### ✅ Fix 1: Redeployed `calendly_webhook_handler`
```bash
export GCP_PROJECT=dosedaily-raw
export GCP_REGION=us-central1
export FIRESTORE_DATABASE_ID=telemeetinglog
bash scripts/deploy_calendly_webhook.sh
```

**Result:** Function now properly configured with:
- `FIRESTORE_DATABASE_ID=telemeetinglog` ✅
- Connected to correct Firestore database ✅
- Will store Zoom links for NEW bookings ✅

### ✅ Fix 2: Redeployed `calendly_reminder_handler`
```bash
export GCP_PROJECT=dosedaily-raw
export GCP_REGION=us-central1
export FIRESTORE_DATABASE_ID=telemeetinglog
export SLACK_WEBHOOK_URL=$(gcloud secrets versions access latest --secret=SLACK_WEBHOOK_URL --project=dosedaily-raw)
bash scripts/deploy_calendly_reminder.sh
```

**Result:** Function now properly configured with:
- `FIRESTORE_DATABASE_ID=telemeetinglog` ✅
- `SLACK_WEBHOOK_URL` from Secret Manager ✅
- Will send Slack reminders for bookings with Zoom links ✅

---

## Current State

### What's Working Now:
1. ✅ **New Calendly bookings** will store Zoom links in Firestore (if Calendly provides them)
2. ✅ **Slack reminders** will be sent 15 minutes before calls (for bookings with Zoom links)
3. ✅ **Firestore storage** is working correctly with the `telemeetinglog` database

### What's Still Broken:
1. ⚠️ **Old bookings** in Firestore are missing Zoom links (created before 2026-03-16 fix)
2. ⚠️ **Some bookings** are missing `event_start_utc` (Calendly API didn't return it)
3. ⚠️ **Prefill form** still has placeholder values (needs actual Google Form entry IDs)

---

## Next Steps

### Immediate Actions Needed:

#### 1. Test with a New Booking
Create a test Calendly booking to verify:
- Zoom link is extracted and stored in Firestore
- Slack reminder is sent 15 minutes before the call
- All data is properly stored

#### 2. Fix Prefill Form Configuration
The current deployment has placeholder values:
```
PREFILL_FORM_BASE_URL: https://docs.google.com/forms/d/e/YOUR_FORM_ID/viewform
PREFILL_FORM_ENTRY_EMAIL: '123456789'
PREFILL_FORM_ENTRY_NAME: '987654321'
```

**To fix:**
1. Get the actual Google Form URL
2. Get the correct entry IDs for email and name fields
3. Redeploy with correct values:
```bash
export PREFILL_FORM_BASE_URL="https://docs.google.com/forms/d/e/ACTUAL_FORM_ID/viewform"
export PREFILL_FORM_ENTRY_EMAIL="ACTUAL_EMAIL_ENTRY_ID"
export PREFILL_FORM_ENTRY_NAME="ACTUAL_NAME_ENTRY_ID"
bash scripts/deploy_calendly_webhook.sh
```

#### 3. Monitor Logs
Check Cloud Function logs for new bookings:
```bash
gcloud functions logs read calendly_webhook_handler --project=dosedaily-raw --limit=50
```

Look for:
- "Zoom join URL extracted: https://..."
- "Stored prefilled link in Firestore doc..."
- Any errors or warnings

#### 4. Optional: Backfill Old Bookings
If you need Zoom links for old bookings, you would need to:
1. Query Calendly API for past events
2. Extract Zoom links
3. Update Firestore documents

This is only needed if you want to send reminders for old bookings.

---

## Verification Checklist

- [x] `calendly_webhook_handler` has `FIRESTORE_DATABASE_ID=telemeetinglog`
- [x] `calendly_reminder_handler` has `FIRESTORE_DATABASE_ID=telemeetinglog`
- [x] `calendly_reminder_handler` has `SLACK_WEBHOOK_URL` configured
- [x] Firestore `calendly_prefilled_forms` collection is accessible
- [ ] Test new booking creates Firestore document with Zoom link
- [ ] Test Slack reminder is sent 15 minutes before call
- [ ] Update prefill form configuration with actual values
- [ ] Monitor logs for any errors

---

## Technical Details

### Firestore Sample Data
```python
Document ID: 0306b7de-3c6a-421f-9620-a882ba8c2baf_6598d850-5ced-41d0-8a19-4c102ca8bc3a
  - Invitee Email: shivangi@dosedaily.co
  - Invitee Name: test
  - Event Start: 2026-03-13T15:30:00.000000Z
  - Zoom Join URL: https://us06web.zoom.us/j/83031051483?pwd=...
  - Prefilled Form URL: https://docs.google.com/forms/d/e/...
  - Reminder Sent: Not sent
```

### Environment Variables (Current)

**calendly_webhook_handler:**
```yaml
FIRESTORE_DATABASE_ID: telemeetinglog
GCP_PROJECT: dosedaily-raw
PREFILL_FORM_BASE_URL: https://docs.google.com/forms/d/e/YOUR_FORM_ID/viewform
PREFILL_FORM_ENTRY_EMAIL: '123456789'
PREFILL_FORM_ENTRY_NAME: '987654321'
```

**calendly_reminder_handler:**
```yaml
FIRESTORE_DATABASE_ID: telemeetinglog
GCP_PROJECT: dosedaily-raw
SLACK_WEBHOOK_URL: https://hooks.slack.com/services/T01AZT0P12T/B09TXNCJU5D/...
```

---

## References

- **Code:** `functions/calendly/main.py` (lines 54-113: `_extract_zoom_join_url()`)
- **Code:** `functions/calendly_reminder/main.py` (lines 42-73: `_send_slack()`)
- **Changelog:** `CHANGELOG.md` (2026-03-16: Fix: Slack reminder missing Zoom link)
- **Deploy Scripts:** 
  - `scripts/deploy_calendly_webhook.sh`
  - `scripts/deploy_calendly_reminder.sh`
