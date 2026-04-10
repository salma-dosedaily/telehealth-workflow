# Prefill Google Form from Calendly (Patient Email + Name)

When a patient books via Calendly, the webhook can build a **prefilled Google Form URL** with **Patient Email** and **Patient Name** so Kim only has to fill **Kim's Note**, **Call duration**, and **Meeting UUID** (paste after the Zoom call).

**Meeting UUID** is **not** available at booking time (it comes from Zoom when the meeting ends). Kim pastes the Zoom meeting link or UUID when she submits the form after the call.

---

## 1. Get your form’s entry IDs

Google Form prefilled URLs use `entry.ENTRY_ID=value`. You need the entry ID for each field you want to prefill.

**Option A – From the form (easiest)**  
1. Open the form in edit mode.  
2. Click **Responses** → **⋮** (three dots) → **Get pre-filled link**.  
3. Fill **only Patient Email** with `test@test.com` (leave Patient Name and Kim's Note blank). Click **Get link**. The URL has one `entry.XXXXX=...` — that is the **email** entry ID.  
4. Repeat: fill **only Patient Name** with `Test` (clear email and Kim's Note). Click **Get link**. The URL has one `entry.YYYYY=...` — that is the **name** entry ID.  
5. Do **not** fill Kim's Note in the prefill dialog. We only prefill email and name; Kim's Note must stay empty.  
6. Set `PREFILL_FORM_ENTRY_EMAIL` to the email ID and `PREFILL_FORM_ENTRY_NAME` to the name ID. If you mix them up (e.g. use Kim's Note's ID for name), the patient name will appear in Kim's Note.

**Option B – From Apps Script**  
Use `FormApp.getActiveForm()`, create a response with default answers, then `toPrefilledUrl()` and parse the `entry.XXXXX` parts. See [Google Form entry IDs](https://stackoverflow.com/questions/46017170/get-entry-id-which-is-used-to-pre-populate-fields-in-a-google-form-url).

---

## 2. Add column to BigQuery (if you want the URL stored)

The Calendly function writes a row to `telehealth.calendly_bookings`. To store the prefilled URL there, add a column:

```sql
ALTER TABLE `dosedaily-raw.telehealth.calendly_bookings`
ADD COLUMN IF NOT EXISTS prefilled_form_url STRING;
```

If you don’t add this column, the function will still run but BigQuery may reject the insert (extra field) and the webhook can return 500. Add the column before enabling prefill so new bookings get the URL in BQ.

---

## 3. Set env vars and redeploy the Calendly function

Set these in the Calendly Cloud Function (and redeploy):

| Env var | Required | Example | Description |
|--------|----------|---------|-------------|
| `PREFILL_FORM_BASE_URL` | Yes (for prefill) | `https://docs.google.com/forms/d/ABC123xyz/viewform` | Form URL up to and including `viewform`. |
| `PREFILL_FORM_ENTRY_EMAIL` | Yes (for prefill) | `123456789` | Entry ID for the “Patient Email” field. |
| `PREFILL_FORM_ENTRY_NAME` | No | `987654321` | Entry ID for the “Patient Name” field. |
| `FIRESTORE_DATABASE_ID` | No | `telemeetinglog` | Same as Zoom; prefilled links in Firestore so you can look up by patient email without BQ. |
| `SENDGRID_FROM_EMAIL` | No (for email) | `noreply@yourdomain.com` | Verified sender in SendGrid; required when emailing Kim the prefilled link. |
| `HOST_EMAIL` | No | `kim@yourdomain.com` | Fallback recipient when Calendly doesn't return host_email; otherwise we email the Calendly host. |

**Redeploy with prefill (Telehealth Note form):**

Use your form’s **base URL** (no `?usp=header`) and the **entry IDs** you get from “Get pre-filled link” (see section 1). The numbers below are placeholders — replace them with the real IDs from your form’s prefill URL.

```bash
export PREFILL_FORM_BASE_URL="https://docs.google.com/forms/d/e/1FAIpQLSdWMAFl0ymLUjKJI963tVmpGfUiZBfM-bPxsr3CvuGLXvBi0A/viewform"
export PREFILL_FORM_ENTRY_EMAIL="REPLACE_WITH_EMAIL_ENTRY_ID"
export PREFILL_FORM_ENTRY_NAME="REPLACE_WITH_NAME_ENTRY_ID"
# Optional: same DB as Zoom so prefilled links are in Firestore (look up by invitee_email)
export FIRESTORE_DATABASE_ID="telemeetinglog"
./scripts/deploy_calendly_webhook.sh
```

The webhook reads **invitee_email** and **invitee_name** from the Calendly API and builds the prefilled URL; that URL is stored in **BigQuery** (`prefilled_form_url`) and in **Firestore** (collection `calendly_prefilled_forms`) so you can get it without querying BQ.

Or set the vars in Cloud Console: Cloud Functions → calendly_webhook_handler → Edit → Environment variables.

---

## 4. How Kim gets and uses the prefilled link

The form does **not** open by itself. Kim (or a dashboard/tool) must open the prefilled URL. The link is stored in two places so you don’t have to rely only on BigQuery:

1. **When a patient books:** The invitee fills Name and Email on the Calendly page and clicks **Book meeting**. Calendly then sends a webhook; we use the **name and email from that booking** (via Calendly API, with payload fallback) to build the prefilled URL. So the URL always reflects the person who just booked. The webhook writes a row to BigQuery and to Firestore **`calendly_prefilled_forms`** (when `FIRESTORE_DATABASE_ID` is set). Each doc has `invitee_email`, `invitee_name`, `prefilled_form_url`, `event_start_utc`, and `created_at`.
2. **Getting the link (no need to “grab from BQ” every time):**
   - **Slack 15-min reminder (recommended, free):** Kim gets a Slack message ~15 min before each call with the prefilled link. See section 6.
   - **Google Sheet from BigQuery:** A Sheet synced with the bookings table so Kim clicks the link for each row. See section 7. No billing.
   - **By email:** When you enable SendGrid (see section 5), Kim receives an email. (SendGrid may require a billed account.)
   - **From Firestore:** Query by `invitee_email` (e.g. “latest booking for this patient”) and use the `prefilled_form_url` from that doc. Same Firestore DB as Zoom (`FIRESTORE_DATABASE_ID=telemeetinglog`) so one place for both Zoom meeting data and Calendly prefill links.
   - **From BigQuery:** Run a query or use Looker Studio / Sheets on `telehealth.calendly_bookings` and open `prefilled_form_url` for the booking.
3. **When Kim opens the link:** The form opens with **Patient Email** and **Patient Name** already filled. She fills **Kim's Note**, **Call duration (minutes)**, and **Meeting UUID** (paste Zoom link after the call), then submits.

Meeting UUID cannot be prefilled from Calendly; it is only known after the Zoom meeting. Kim pastes it when submitting the form.

---

## 5. Email the prefilled link to Kim (optional)

When someone books, the webhook can **email Kim the prefilled form link** so she gets it in her inbox and can click to open the form after the call. No need to look up BQ or Firestore.

**Prerequisites:**
- [SendGrid](https://sendgrid.com/) account (free tier: 100 emails/day).
- A verified sender email (single sender or domain).

**Setup:**

1. **Create a SendGrid API key**
   - SendGrid → Settings → API Keys → Create API Key.
   - Name it (e.g. `calendly-telehealth`), choose "Restricted Access" → Mail Send: Full Access (or at least "Mail Send").
   - Copy the key (shown once).

2. **Store the API key in Google Secret Manager**
   ```bash
   echo -n "SG.xxxx_your_api_key" | gcloud secrets create SENDGRID_API_KEY --data-file=- --project=dosedaily-raw
   gcloud secrets add-iam-policy-binding SENDGRID_API_KEY \
     --member="serviceAccount:dosedaily-raw@appspot.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor" --project=dosedaily-raw
   ```
   Use the same service account that has access to `CALENDLY_PERSONAL_ACCESS_TOKEN` (check IAM for that secret).

3. **Verify your sender email in SendGrid**
   - SendGrid → Settings → Sender Authentication → Single Sender Verification (or Domain Authentication).
   - Add and verify the email you'll use as the "from" address (e.g. `noreply@dosedaily.co`).

4. **Deploy with email env vars**
   ```bash
   export PREFILL_FORM_BASE_URL="https://docs.google.com/forms/d/e/1FAIpQLSdWMAFl0ymLUjKJI963tVmpGfUiZBfM-bPxsr3CvuGLXvBi0A/viewform"
   export PREFILL_FORM_ENTRY_EMAIL="1104708604"
   export PREFILL_FORM_ENTRY_NAME="350050506"
   export SENDGRID_FROM_EMAIL="noreply@dosedaily.co"   # Must be verified in SendGrid
   export HOST_EMAIL="kim@dosedaily.co"               # Where to send the link (or we use Calendly host)
   ./scripts/deploy_calendly_webhook.sh
   ```

**Who receives the email?** The Calendly event host (from the API) is used as the recipient. If Calendly doesn't return `host_email`, we fall back to `HOST_EMAIL`. Set `HOST_EMAIL` to Kim's address if you want to always send to her regardless of who owns the Calendly event.

**Email content:** Subject includes patient name and event time; body has a clickable "Open prefilled Telehealth Note form" link. Kim clicks it, fills notes + duration + Meeting UUID, and submits.

---

## 6. Slack 15-min reminder (recommended, free)

Kim gets a **Slack message ~15 min before each call** with the prefilled form link. No billing—uses Slack Incoming Webhook.

**Setup:**

1. **Create a Slack Incoming Webhook**
   - Slack → Apps → Incoming Webhooks → Add to Slack.
   - Choose the channel (e.g. `#telehealth` or a DM channel).
   - Copy the webhook URL (e.g. `https://hooks.slack.com/services/T.../B.../xxx`).

2. **Deploy the reminder function and scheduler**
   ```bash
   export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
   export FIRESTORE_DATABASE_ID="telemeetinglog"
   export REMINDER_SECRET="your_random_secret"  # Optional; protects the endpoint
   ./scripts/deploy_calendly_reminder.sh
   ./scripts/setup_calendly_reminder_scheduler.sh
   ```

3. **Grant Cloud Scheduler permission** (if you get 403):
   - Cloud Console → Cloud Run → `calendly-reminder-handler` → Security → Add principal.
   - Add `PROJECT_NUMBER-compute@developer.gserviceaccount.com` with role **Cloud Run Invoker**.
   - Or enable "Allow unauthenticated" for the reminder function.

The scheduler runs every 5 min and sends a Slack message for bookings whose `event_start` is in the next 15 min. Each booking is reminded only once (`reminder_sent_at` is set after sending).

---

## 7. Google Sheet feed from BigQuery (free)

Connect BigQuery `telehealth.calendly_bookings` to a Google Sheet so Kim can open the sheet and click the prefilled link for each booking. No code changes—data is already in BQ.

**Option A – BigQuery Studio / Looker Studio**
1. BigQuery → select `telehealth.calendly_bookings`.
2. Explore data → Open in Looker Studio.
3. Create a report with columns: `invitee_name`, `invitee_email`, `event_start`, `prefilled_form_url` (as a link).
4. Kim opens the report and clicks the link for the booking she needs.

**Option B – Connected Sheets**
1. BigQuery → select `telehealth.calendly_bookings` → Export → Export to Google Sheets.
2. Or: Create a Connected Sheet (BigQuery → Data Canvas → Connect to Sheets) for live sync.
3. Add a filter (e.g. `event_start >= TODAY()`) so Kim sees only upcoming bookings.
4. Format `prefilled_form_url` as a hyperlink so she can click to open the form.

**Option C – Scheduled query + export**
1. Create a saved query that selects recent bookings (e.g. `WHERE event_start >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)`).
2. Schedule the query to run daily (or hourly) and export results to a Sheet.
3. Kim bookmarks the Sheet and uses it to get the link before each call.

---

## Summary

| Prefilled from Calendly | Filled by Kim |
|-------------------------|----------------|
| Patient Email           | Kim's Note     |
| Patient Name            | Call duration (minutes) |
| —                       | Meeting UUID (paste after call) |

The Calendly function builds the URL from invitee email and name, stores it in BigQuery (`prefilled_form_url`) and in Firestore (`calendly_prefilled_forms`) when env vars are set. Use Firestore to look up the link by patient email without querying BQ.

---

## Troubleshooting: Form doesn't prefill when I open the link

**1. Are you opening the prefilled link for this booking?**  
The name and email in the URL come from the Calendly booking page (the person who clicked "Book meeting"). Open the **`prefilled_form_url`** for that booking—the row whose `invitee_email` / `invitee_name` match the guest. Using a link from an old or test booking shows the wrong name/email. The normal Calendly “booking confirmation” link is not the form link. In BigQuery: run  
`SELECT invitee_email, invitee_name, prefilled_form_url FROM \`dosedaily-raw.telehealth.calendly_bookings\` ORDER BY event_start DESC LIMIT 5`  
and open the **prefilled_form_url** in your browser.

**2. Was the booking created after you set the env vars and redeployed?**  
Prefilled URLs are only generated for bookings that happen **after** the Calendly function is deployed with `PREFILL_FORM_BASE_URL` and `PREFILL_FORM_ENTRY_EMAIL` set. For older rows, `prefilled_form_url` may be null. Create a new test booking after deploy and use that row’s link.

**3. Are the entry IDs correct for your form?**  
The entry IDs in the URL must match **your** form. Get them again: form edit → **Responses** → **⋮** → **Get pre-filled link** → fill Patient Email and Patient Name → **Get link**. In the URL you’ll see `entry.XXXXXXXXX=...` and `entry.YYYYYYYYY=...`. Those numbers (and their order: which is email, which is name) must match what you set in `PREFILL_FORM_ENTRY_EMAIL` and `PREFILL_FORM_ENTRY_NAME`. If they’re wrong or swapped, the form won’t prefill. Update the env vars and redeploy.

**4. Check the URL in the table**  
Open the stored `prefilled_form_url` in a new tab. It should look like:  
`https://docs.google.com/forms/d/e/.../viewform?entry.123456789=email%40example.com&entry.987654321=Name`  
If it has `entry.` params but the form still doesn’t prefill, the entry IDs don’t match your form’s current fields (re-get them from “Get pre-filled link” and redeploy).

**5. POST 200 but no prefilled link in BigQuery**  
- Ensure the table has column `prefilled_form_url` (see section 2). If the column was missing, the insert can fail with 500; if you still got 200, the row may be from before prefill was enabled.  
- Check Cloud Logging for this function: look for **"Prefilled form URL built for …"** and **"Stored prefilled link in Firestore doc …"**. If you see those, the URL was built and stored in Firestore even if BQ doesn't show it.  
- Get the link from **Firestore** instead: collection `calendly_prefilled_forms`, query by `invitee_email` and use the latest doc's `prefilled_form_url`. Use the same `FIRESTORE_DATABASE_ID` as Zoom (e.g. `telemeetinglog`) and redeploy the Calendly function with that env var set.

**6. Kim doesn't receive the prefilled-link email**  
- Ensure `SENDGRID_FROM_EMAIL` and `HOST_EMAIL` (or Calendly returns `host_email`) are set and redeployed.  
- Verify `SENDGRID_API_KEY` exists in Secret Manager and the Cloud Functions service account has `secretAccessor`.  
- Check Cloud Logging for "Sent prefilled form link email to …" (success) or "SendGrid failed" / "SendGrid email failed" (error).  
- SendGrid: verify the sender email/domain in SendGrid, and check Activity for bounces or blocks.

**7. Kim's note is prefilled with patient name**  
`PREFILL_FORM_ENTRY_NAME` is set to the **Kim's Note** field's entry ID instead of the **Patient Name** field's. Fix: re-get the entry IDs (see section 1). Fill **only** Patient Email to get the email ID, then **only** Patient Name to get the name ID. Do not use any entry ID that corresponds to Kim's Note. Update the env vars and redeploy.
