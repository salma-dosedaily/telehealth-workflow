# Four New Telehealth Automation Features

**Date:** 2026-03-27 — Updated 2026-04-03
**Status:** Implemented and deployed

---

## Overview

Four major enhancements have been added to the telehealth automation system to improve patient tracking, enable product-specific follow-up flows, handle no-shows, and preserve formatting in Kim's notes.

---

## Feature 1: Product Information in Zoom Flow

### What It Does
Automatically extracts product type (Liver, Cholesterol, Bundle) from Zoom meeting topics and passes it through the entire pipeline, enabling product-specific Klaviyo follow-up flows.

### How It Works

#### Zoom Meeting.ended Flow:
1. When a Zoom call ends, the system checks the meeting topic
2. Detects keywords: "liver", "cholesterol", or "bundle" (case-insensitive)
3. Sets `productName` in the RudderStack event
4. Stores `product_name` in Firestore for later retrieval

#### Google Form Flow:
1. If form includes product field → uses that value
2. If form doesn't include product BUT has meeting_uuid → retrieves from Firestore
3. Passes `productName` to RudderStack/Klaviyo

### Klaviyo Setup
Create flow splits based on event property:
```
Event: Telehealth_Call_Finished
Condition: productName contains "Liver"
  → Send Liver-specific follow-up email

Event: Telehealth_Call_Finished  
Condition: productName contains "Cholesterol"
  → Send Cholesterol-specific follow-up email

Event: Telehealth_Call_Finished
Condition: productName contains "Bundle"
  → Send Bundle-specific follow-up email
```

### Calendly Setup
Set your Calendly event names to include product keywords:
- "Liver Health Consultation"
- "Cholesterol Management Session"
- "Bundle Program Follow-up"

These names sync to Zoom meeting topics automatically.

### Example Event Payload
```json
{
  "event": "Telehealth_Call_Finished",
  "userId": "patient@example.com",
  "properties": {
    "email": "patient@example.com",
    "name": "Jane Doe",
    "productName": "Liver",
    "Product": "Liver",
    "duration": 15,
    "attended": true,
    "source": "google_form"
  }
}
```

---

## Feature 2: No-Show Handling

### What It Does
Handles two no-show scenarios:

1. **Automatic (Zoom-based):** When a Zoom call ends in under 10 minutes, a `Telehealth_Call_No_Show` event is sent automatically.
2. **Manual (Form-based — added 2026-04-03):** Kim can select **"No Show"** from the Product/Program dropdown on the Google Form. This fires `Telehealth_Call_Finished` with `productName = "No Show"` and `attended = false`, routing the patient to the "We Missed You" email inside the existing Klaviyo flow. Only the patient email is required — no notes or duration needed.

### How It Works

#### Automatic (Zoom duration-based):
- **Old behavior:** Calls < 5 min were ignored (no event sent)
- **Current behavior:**
  - Calls < 10 min → `Telehealth_Call_No_Show` event (`attended: false`)
  - Calls ≥ 10 min → `Telehealth_Call_Finished` event (`attended: true`)

#### Manual (Google Form):
1. Kim selects **No Show** from the Product/Program dropdown
2. The App Script detects it (`productName.toLowerCase().replace(/[-\s]/g,"") === "noshow"`) and sends the payload without requiring notes or duration
3. The Cloud Function (`process_form_submission`) canonicalises it to `"No Show"` via `_canonical_product_name_for_klaviyo()`, bypasses note/duration validation, and fires `Telehealth_Call_Finished` with `productName = "No Show"` and `attended = false`
4. A RudderStack identify is sent with `telehealth_last_product = "No Show"` and `completed_call = False`

#### Event Properties — Automatic no-show (Zoom):
```json
{
  "event": "Telehealth_Call_No_Show",
  "userId": "meeting_uuid_12345",
  "properties": {
    "meeting_uuid": "meeting_uuid_12345",
    "host_email": "kim@dosedaily.com",
    "duration": 3,
    "meeting_date": "2026-03-27T14:30:00Z",
    "source": "zoom_meeting_ended",
    "attended": false,
    "productName": "Liver"
  }
}
```

#### Event Properties — Manual no-show (Google Form):
```json
{
  "event": "Telehealth_Call_Finished",
  "userId": "patient@example.com",
  "properties": {
    "email": "patient@example.com",
    "name": "Jane Doe",
    "productName": "No Show",
    "Product": "No Show",
    "attended": false,
    "duration": 10,
    "source": "google_form",
    "submitted_at": "2026-04-03T15:46:35Z"
  }
}
```

### Why `Telehealth_Call_Finished` (not `Telehealth_Call_No_Show`) for form no-shows

The Google Form only fires `Telehealth_Call_Finished`. Using a single event name for all form submissions keeps the Klaviyo flow simple — one trigger, one Conditional Split at the top routes on `productName`. A separate event would require Kim's form submissions to enter a different flow entirely, which adds maintenance overhead.

Zoom automatic no-shows still use `Telehealth_Call_No_Show` because they come from a different code path and Zoom doesn't provide a patient email.

### Klaviyo Setup

#### For manual no-shows (form path):
Inside the existing `Telehealth_Call_Finished` flow, add a **Conditional Split** immediately after the trigger:
- Condition type: **What someone has done (or not done)**
- Has done: `Telehealth_Call_Finished` where `productName` **equals** `No Show` — **at least once** — **in the last 2 hours**
- **YES branch** → "We Missed You" email
- **NO branch** → existing product split (Liver / Cholesterol / Bundle)

#### For automatic no-shows (Zoom path — optional separate flow):
1. **Trigger:** Metric `Telehealth_Call_No_Show`
2. **Wait:** 1 hour
3. **Email:** "We missed you — reschedule your consultation" with Calendly link

### Use Cases
- **Manual no-show from form:** Kim logs a no-show in under 30 seconds; "We Missed You" email fires automatically
- **Automatic no-show from Zoom:** Short/dropped calls trigger reschedule reminder without any action from Kim
- **Analytics:** Track no-show rates by source (`google_form` vs `zoom_meeting_ended`)

---

## Feature 3: Profile Property for Completed Calls

### What It Does
Sets a Klaviyo profile property `completed_telehealth_call: true` when a patient completes a call via the Google Form, enabling segmentation and targeting.

### How It Works

#### Identify Call:
When the Google Form is submitted, the system sends:
```json
{
  "userId": "patient@example.com",
  "traits": {
    "email": "patient@example.com",
    "firstName": "Jane",
    "lastName": "Doe",
    "completed_telehealth_call": true
  }
}
```

This updates the Klaviyo profile with the property.

### Klaviyo Segmentation

#### Create Segment: "Completed Telehealth Patients"
- Go to Klaviyo → Lists & Segments → Create Segment
- Condition: `Properties about someone` → `completed_telehealth_call` = `true`
- Use this segment for:
  - Upsell campaigns (they've already engaged)
  - Testimonial requests
  - Referral programs
  - Exclude from "book your first call" campaigns

#### Create Segment: "Never Completed Call"
- Condition: `Properties about someone` → `completed_telehealth_call` does not exist OR = `false`
- Use for:
  - "Book your first consultation" campaigns
  - Educational content to build trust
  - Special first-time offers

### Use Cases
1. **Lifecycle marketing:** Different messaging for first-time vs. returning patients
2. **Exclusion lists:** Don't send "book your first call" to patients who already completed one
3. **Analytics:** Track conversion rate from booking to completed call
4. **Retention:** Target patients who completed one call but haven't booked a second

---

## Feature 4: Bullet Points in Kim's Notes

### What It Does
Preserves line breaks, bullet points, and formatting in Kim's notes so they display correctly in Klaviyo emails.

### How It Works

#### Before (Old Behavior):
```
Input:  "Patient needs:
         - More protein
         - Less sugar
         - Daily walks"

Output: "Patient needs: - More protein - Less sugar - Daily walks"
```
All formatting was stripped, making notes hard to read.

#### After (New Behavior):
```
Input:  "Patient needs:
         - More protein
         - Less sugar
         - Daily walks"

Output: "Patient needs:
         - More protein
         - Less sugar
         - Daily walks"
```
Formatting is preserved with normalized line endings (`\n`).

### Google Form Setup
- Use **Paragraph** field type for "Kim's Note" (not short answer)
- Kim can type or paste multi-line notes with bullet points
- Formatting is automatically preserved

### Klaviyo Email Template
Use the merge variable with HTML line break conversion:

```liquid
{{ event.kims_custom_note|linebreaksbr }}
```

> **Important:** Use `linebreaksbr`, **not** `nl2br` or `newline_to_br` — Klaviyo's `nl2br` can produce template errors. `linebreaksbr` is the correct Klaviyo filter.

Or in plain text emails:
```liquid
{{ event.kims_custom_note }}
```

### Example

**Kim types in form:**
```
Patient goals:
- Reduce cholesterol by 20 points
- Lose 10 lbs in 3 months
- Improve energy levels

Next steps:
1. Start meal plan
2. Schedule follow-up in 4 weeks
```

**Klaviyo email displays:**
```
Patient goals:
- Reduce cholesterol by 20 points
- Lose 10 lbs in 3 months
- Improve energy levels

Next steps:
1. Start meal plan
2. Schedule follow-up in 4 weeks
```

---

## Deployment Instructions

### Step 1: Redeploy Cloud Function
```bash
cd /Users/salmaelmasry/Desktop/telehealth-workflow
export GCP_PROJECT=dosedaily-raw
export GCP_REGION=us-central1
bash scripts/deploy_zoom_webhook.sh
```

### Step 2: Update Google Form (if needed)
- Ensure "Kim's Note" field is **Paragraph** type (not short answer)
- Ensure "Product" field exists (dropdown with options: Liver, Cholesterol, Bundle, **No Show**)
- Paste the latest App Script from `scripts/google_form_to_rudderstack.js` into the Script Editor

### Step 3: Set Up Klaviyo Flows

#### A. Manual No-Show Split (inside `Telehealth_Call_Finished` flow)
1. Open the existing `Telehealth_Call_Finished` flow
2. Add a **Conditional Split** immediately after the trigger
3. Condition: **What someone has done (or not done)** → `Telehealth_Call_Finished` where `productName` **equals** `No Show` — at least once — in the last 2 hours
4. **YES branch** → "We Missed You" email
5. **NO branch** → existing product split

#### B. Automatic No-Show Flow (Zoom-based — optional)
1. Create flow triggered by `Telehealth_Call_No_Show` metric
2. Add 1-hour delay
3. Send reschedule email with Calendly link

#### C. Product-Specific Splits (NO branch of the above split)
1. Already in the `Telehealth_Call_Finished` flow
2. Conditional splits based on `productName`:
   - If `productName` contains "Liver" → Liver email
   - If `productName` contains "Cholesterol" → Cholesterol email
   - If `productName` contains "Bundle" → Bundle email
   - Else → Generic email

#### C. Completed Call Segment
1. Create segment: `completed_telehealth_call` = `true`
2. Use for upsell campaigns
3. Exclude from first-time booking campaigns

### Step 4: Test End-to-End

#### Test 1: Automatic No-Show Event (Zoom)
1. Create test Zoom meeting with topic "Test Liver Consultation"
2. End after 5 minutes
3. Check RudderStack → Klaviyo for `Telehealth_Call_No_Show` event
4. Verify `productName: "Liver"` is included

#### Test 1b: Manual No-Show Event (Google Form)
1. Open the Google Form
2. Enter a patient email; select **No Show** from the Product/Program dropdown
3. Submit (leave notes and duration blank)
4. Check Klaviyo — should see `Telehealth_Call_Finished` event with `productName: "No Show"` and `attended: false`
5. Verify the Conditional Split routes to the YES branch and the "We Missed You" email fires

#### Test 2: Completed Call with Product
1. Create test Zoom meeting with topic "Test Cholesterol Session"
2. End after 15 minutes
3. Submit Google Form with patient email
4. Check Klaviyo profile for `completed_telehealth_call: true`
5. Check event for `productName: "Cholesterol"`

#### Test 3: Bullet Points
1. Submit form with multi-line note:
   ```
   Patient needs:
   - Item 1
   - Item 2
   ```
2. Check RudderStack event payload
3. Verify Klaviyo email displays formatting correctly

---

## Troubleshooting

### Product Not Detected from Zoom
**Symptom:** `productName` is missing in events  
**Cause:** Zoom meeting topic doesn't contain keywords  
**Fix:** Update Calendly event names to include "Liver", "Cholesterol", or "Bundle"

### No-Show Event Not Triggering
**Symptom:** Calls < 10 min don't send events  
**Cause:** Old Cloud Function version deployed  
**Fix:** Redeploy with `bash scripts/deploy_zoom_webhook.sh`

### Profile Property Not Set
**Symptom:** `completed_telehealth_call` not appearing in Klaviyo  
**Cause:** Form submission not reaching Cloud Function  
**Fix:** Check Cloud Function logs: `gcloud functions logs read telehealth_webhook_handler --limit=50`

### Bullet Points Not Displaying
**Symptom:** Notes show as single line in Klaviyo
**Cause:** Email template using wrong filter
**Fix:** Update Klaviyo email template to use `{{ event.kims_custom_note|linebreaksbr }}` — do **not** use `nl2br` or `newline_to_br`

---

## Technical Details

### Code Changes

#### main.py
- `_canonical_product_name_for_klaviyo()`: Maps raw dropdown values to stable names (Liver / Cholesterol / Bundle / **No Show**)
- `send_no_show_to_rudderstack()`: Sends `Telehealth_Call_No_Show` for Zoom duration-based no-shows
- `send_meeting_ended_to_rudderstack()`: Added `product_name` parameter
- `store_meeting_ended()`: Stores `product_name` in Firestore
- `_rudderstack_identify()`: Added `completed_call` and `telehealth_product` parameters; sets `telehealth_last_product` on profile
- `send_form_submission_to_rudderstack()`: Calls identify with `completed_call=True`; uses `email`/`name` (not `patient_*`)
- `process_form_submission()`: Detects `canon_product == "No Show"` early; bypasses note/duration checks; fires `Telehealth_Call_Finished` with `attended=False` for manual no-shows
- `telehealth_webhook_handler()`: Extracts product from Zoom topic, sends no-show events for calls < 10 min

### Firestore Schema Update
```json
{
  "meeting_uuid": "abc123",
  "host_email": "kim@dosedaily.com",
  "duration": 15,
  "start_time": "2026-03-27T14:30:00Z",
  "meeting_id": 89166792057,
  "product_name": "Liver",  // NEW
  "received_at": "2026-03-27T14:31:00Z"
}
```

### Event Payloads

#### Telehealth_Call_Finished — attended call (form)
```json
{
  "event": "Telehealth_Call_Finished",
  "userId": "patient@example.com",
  "properties": {
    "email": "patient@example.com",
    "name": "Jane Doe",
    "kims_custom_note": "• Increase protein\n• Walk 30 min daily",
    "duration": 15,
    "productName": "Liver",
    "Product": "Liver",
    "attended": true,
    "source": "google_form",
    "submitted_at": "2026-04-03T15:46:35Z"
  }
}
```

#### Telehealth_Call_Finished — manual no-show (form)
```json
{
  "event": "Telehealth_Call_Finished",
  "userId": "patient@example.com",
  "properties": {
    "email": "patient@example.com",
    "name": "Jane Doe",
    "productName": "No Show",
    "Product": "No Show",
    "attended": false,
    "duration": 10,
    "source": "google_form",
    "submitted_at": "2026-04-03T15:46:35Z"
  }
}
```

#### Telehealth_Call_No_Show — automatic no-show (Zoom, < 10 min)
```json
{
  "event": "Telehealth_Call_No_Show",
  "userId": "meeting_uuid_12345",
  "properties": {
    "meeting_uuid": "meeting_uuid_12345",
    "host_email": "kim@dosedaily.com",
    "duration": 5,
    "meeting_date": "2026-03-27T14:30:00Z",
    "productName": "Cholesterol",
    "attended": false,
    "source": "zoom_meeting_ended"
  }
}
```

#### Identify Call — attended (profile update)
```json
{
  "userId": "patient@example.com",
  "traits": {
    "email": "patient@example.com",
    "firstName": "Jane",
    "lastName": "Doe",
    "completed_telehealth_call": true,
    "telehealth_call_attended": true,
    "telehealth_attended": "yes",
    "productName": "Liver",
    "telehealth_last_product": "Liver"
  }
}
```

#### Identify Call — manual no-show (profile update)
```json
{
  "userId": "patient@example.com",
  "traits": {
    "email": "patient@example.com",
    "firstName": "Jane",
    "lastName": "Doe",
    "productName": "No Show",
    "telehealth_last_product": "No Show"
  }
}
```

---

## Benefits Summary

1. **Product-Specific Follow-ups:** Send targeted emails based on consultation type (Liver / Cholesterol / Bundle)
2. **No-Show Recovery:** Two paths — automatic (Zoom < 10 min) and manual (Kim selects "No Show" on form). Both route to "We Missed You" email in Klaviyo
3. **Better Segmentation:** Target patients who completed calls vs. those who haven't via `completed_telehealth_call` and `telehealth_last_product` profile traits
4. **Professional Emails:** Properly formatted notes with bullet points using `{{ event.kims_custom_note|linebreaksbr }}`

All four features work together to create a more sophisticated, personalized patient experience while reducing manual work for Kim and the team.
