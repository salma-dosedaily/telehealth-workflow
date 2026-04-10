# Step-by-Step Setup: Telehealth Automation

You have: **Zoom licence**, **Calendly**, **RudderStack admin**. Follow these steps in order so the webhook URL and secrets are ready when each tool needs them.

---

## Prerequisites

- Google Cloud project **dosedaily-raw** (used for telehealth; service account and dataset already created — see [BigQuery & service account](#bigquery--service-account-dosedaily-raw) below).
- `gcloud` CLI installed and logged in, or use Cloud Console.
- This repo (`main.py`, `requirements.txt`) available (e.g. cloned or copied).

### BigQuery & service account (dosedaily-raw)

- **Project:** `dosedaily-raw`
- **Service account (data@dosedaily.co):** `data-dosedaily@dosedaily-raw.iam.gserviceaccount.com`  
  Display name: *Data (data@dosedaily.co)*. GCP requires SA IDs to be 6–30 characters, so the id is `data-dosedaily`.
- **Roles granted:** `roles/bigquery.admin` (create/manage datasets and tables, run jobs), `roles/secretmanager.secretAccessor` (for Cloud Function if run as this SA).
- **Dataset:** `dosedaily-raw.telehealth` (location: **US**). Use this dataset for telehealth events (e.g. RudderStack warehouse, or tables for `Telehealth_Call_Finished`, Calendly bookings).

---

## Part 1 — Google Cloud (Cloud Function + Secrets)

### Step 1.1 — Create or select a GCP project

For this workflow we use **dosedaily-raw** (dataset `telehealth` and service account `data-dosedaily` already exist).

```bash
gcloud config set project dosedaily-raw
```

### Step 1.2 — Enable required APIs

```bash
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable eventarc.googleapis.com
```

### Step 1.3 — Create secrets in Secret Manager

RudderStack secrets are already created for **dosedaily** (data plane `https://dosedaily.dataplane.rudderstack.com`). For Zoom, create or update:

```bash
# Zoom webhook secret (from Zoom app in Step 2.3)
echo -n "PASTE_ZOOM_SECRET_HERE" | gcloud secrets create ZOOM_SECRET_TOKEN --data-file=-

# RudderStack (already in GSM for dosedaily-raw):
# - RUDDERSTACK_URL = https://dosedaily.dataplane.rudderstack.com/v1/track
# - RUDDERSTACK_WRITE_KEY = your HTTP source write key (Basic auth)
```

**Optional (for AI fallback):**

```bash
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY --data-file=-
```

If you skip Gemini, the function still works with regex-only extraction for `kims_custom_note`.

### Step 1.4 — Deploy the Cloud Function

From the **project root** (where `main.py` and `requirements.txt` are):

```bash
gcloud functions deploy telehealth_webhook_handler \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --source=. \
  --entry-point=telehealth_webhook_handler \
  --trigger-http \
  --allow-unauthenticated \
  --set-secrets=ZOOM_SECRET_TOKEN=ZOOM_SECRET_TOKEN:latest,RUDDERSTACK_URL=RUDDERSTACK_URL:latest,RUDDERSTACK_WRITE_KEY=RUDDERSTACK_WRITE_KEY:latest
```

**If you use Gemini**, add to the same command:

```bash
  --set-secrets=...,GEMINI_API_KEY=GEMINI_API_KEY:latest
```

**Optional env:**

```bash
  --set-env-vars=USE_AI=False
```

(Set `USE_AI=True` or omit to use Gemini when the key is present.)

After deployment, copy the **Function URL** (e.g. `https://us-central1-YOUR_PROJECT.cloudfunctions.net/telehealth_webhook_handler`). You need it for Zoom and for testing.

### Step 1.5 — Grant the Cloud Function access to secrets

If the function runs as the default compute service account, grant it access to the secrets:

```bash
PROJECT_ID=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

gcloud secrets add-iam-policy-binding ZOOM_SECRET_TOKEN \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding RUDDERSTACK_URL \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding RUDDERSTACK_WRITE_KEY \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Repeat for `GEMINI_API_KEY` if you created that secret.

---

## Part 2 — Zoom (App + Cloud Recording + Transcript)

### Step 2.1 — Enable Cloud Recording and Audio Transcript

1. Sign in to **Zoom** as an **admin**.
2. Go to **Admin → Account Management → Account Settings** (or **Settings** in the Zoom web portal).
3. Under **Recording**, turn on **Cloud recording**.
4. Under **Recording → Cloud recording**, enable **Audio transcript** (so Zoom generates the transcript we use).
5. Ensure the **nutritionist’s meetings** use Cloud Recording (per meeting or account default).

### Step 2.2 — Create a Zoom app (event subscription)

1. Go to **Zoom App Marketplace**: https://marketplace.zoom.us/
2. **Develop → Build App**.
3. Choose **Event subscription** (or **Webhook only** if available).
4. App name: e.g. `Telehealth Automation`.
5. Company and developer info as required; create the app.

### Step 2.3 — Configure the webhook

1. In the app, open **Feature → Event subscription**.
2. **Enable** the subscription.
3. **Event notification endpoint URL:** paste your **Cloud Function URL** from Step 1.4 (e.g. `https://us-central1-YOUR_PROJECT.cloudfunctions.net/telehealth_webhook_handler`).
4. Click **Validate** (Zoom sends `endpoint.url_validation`; the function must return the encrypted token).  
   - If validation fails: confirm the function is deployed, `ZOOM_SECRET_TOKEN` is set in Secret Manager and matches the **Secret Token** shown in Zoom (Step 2.4).
5. Under **Subscribe to events**, add:
   - **Meeting → Meeting ended** (`meeting.ended`).
   - *(Poll path only: no transcript_completed. Zoom API auth required for poll; see ZOOM_FAST_PATH_SETUP.md.)*
6. Save.

### Step 2.4 — Get the Secret Token and store it in GCP

1. In the same **Event subscription** page, find **Secret Token** (or **Verification token**).
2. Copy it.
3. Update the secret in Google Cloud (replace the placeholder):

```bash
echo -n "YOUR_ACTUAL_ZOOM_SECRET_TOKEN" | gcloud secrets versions add ZOOM_SECRET_TOKEN --data-file=-
```

4. Redeploy the function once so it picks up the new secret (or use the latest version; Gen2 usually reads `:latest` automatically).

### Step 2.5 — Install / activate the app

1. In the Zoom app, go to **Activation** (or **Install**).
2. Activate the app for your account (or for the account that hosts the telehealth meetings).
3. Confirm the app is **activated** so Zoom can send events to your endpoint.

---

## Part 3 — RudderStack (Webhook source + BigQuery + Klaviyo)

### Step 3.1 — Create an HTTP / Webhook source

1. In **RudderStack** (as admin), go to **Sources**.
2. **Add source** → choose **HTTP API** or **Webhook** (or **Custom** if that’s how your plan exposes a webhook).
3. Name: e.g. `Telehealth Zoom Webhook`.
4. Create the source.

### Step 3.2 — Get the webhook URL and write key

1. Open the new source.
2. Copy the **Write Key** (e.g. `3APIeXDybHy1OGhflugQM1sWJo7`).
3. **Data Plane URL**: For dosedaily, use `https://dosedaily.dataplane.rudderstack.com`. The Track endpoint is `.../v1/track`.
4. **Secrets** (already in GSM for dosedaily-raw):
   - `RUDDERSTACK_URL` = `https://dosedaily.dataplane.rudderstack.com/v1/track`
   - `RUDDERSTACK_WRITE_KEY` = your HTTP source write key (sent as Basic auth per [RudderStack HTTP API](https://www.rudderstack.com/docs/api/http-api/)).

```bash
# Secrets RUDDERSTACK_URL and RUDDERSTACK_WRITE_KEY exist in dosedaily-raw. Function uses /v1/track and Basic auth.
```

The Cloud Function POSTs a single track event; format matches the Track API.

### Step 3.3 — Connect BigQuery (warehouse)

1. In RudderStack, go to **Warehouses** (or **Destinations** for a warehouse).
2. Add **BigQuery**; authorize with your GCP project / service account (`data@dosedaily.co` or the one RudderStack uses).
3. Choose dataset (e.g. `telehealth` or `analytics`); create the dataset in BigQuery first if needed.
4. Connect this warehouse to the **Telehealth Zoom Webhook** source so events are persisted to BigQuery.

### Step 3.4 — Connect Klaviyo (destination)

1. In RudderStack, go to **Destinations** (or **Connections**).
2. Add **Klaviyo**; connect with your Klaviyo credentials (API key, etc.).
3. Connect Klaviyo to the same **Telehealth Zoom Webhook** source.
4. Map the event: ensure **Telehealth_Call_Finished** is sent as a track event and that **userId** (or external ID) is set so Klaviyo can identify the profile (e.g. email). Identity resolution (Zoom `meeting_uuid` → patient email) can be done in RudderStack or BigQuery and then synced; see Part 5.

---

## Part 4 — Calendly (so you can resolve patient email)

The Cloud Function does **not** receive patient email from Zoom; you get it from Calendly and join in BigQuery or RudderStack.

### Step 4.1 — Get Calendly API token

1. Log in to **Calendly** (with the account that receives the bookings, e.g. data@dosedaily.co or the nutritionist’s account).
2. Go to **Integrations → API & Webhooks** (or **Developer** section); may require Teams.
3. Create a **Personal Access Token** (or OAuth app if you prefer).
4. Save the token securely; you will use it to sync events to RudderStack or BigQuery (e.g. via a small Cloud Function or RudderStack Calendly source).

### Step 4.2 — Calendly webhook Cloud Function → BigQuery

RudderStack has no Calendly source. Use a Calendly webhook + Cloud Function:

1. **Deploy the Calendly webhook Cloud Function** (from `functions/calendly`):

```bash
cd functions/calendly
gcloud functions deploy calendly_webhook_handler \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --source=. \
  --entry-point=calendly_webhook_handler \
  --trigger-http \
  --allow-unauthenticated \
  --set-secrets=CALENDLY_PERSONAL_ACCESS_TOKEN=CALENDLY_PERSONAL_ACCESS_TOKEN:latest \
  --set-env-vars=GCP_PROJECT=dosedaily-raw \
  --project=dosedaily-raw
```

2. **Copy the Calendly Function URL** (e.g. `https://calendly-webhook-handler-pshv76iija-uc.a.run.app`).

3. **Register the webhook with Calendly** (Calendly has no UI for "connect Cloud Function" — you register via API):

```bash
# Option A: token from Secret Manager via script
python scripts/register_calendly_webhook.py --url "YOUR_CALENDLY_CF_URL" --from-secret-manager

# Option B: token from Secret Manager via env
CALENDLY_PERSONAL_ACCESS_TOKEN=$(gcloud secrets versions access latest --secret=CALENDLY_PERSONAL_ACCESS_TOKEN --project=dosedaily-raw)
python scripts/register_calendly_webhook.py --url "YOUR_CALENDLY_CF_URL"
```

**If the secret doesn't exist yet:** `echo -n "YOUR_CALENDLY_PAT" | gcloud secrets create CALENDLY_PERSONAL_ACCESS_TOKEN --data-file=- --project=dosedaily-raw`  
**If you get "Secret already exists":** the secret is already there. To update the token value use: `echo -n "YOUR_NEW_PAT" | gcloud secrets versions add CALENDLY_PERSONAL_ACCESS_TOKEN --data-file=- --project=dosedaily-raw`

4. **Data flow**: Calendly POSTs `invitee.created` / `invitee.canceled` to your Cloud Function → function fetches invitee details via Calendly API → writes to `dosedaily-raw.telehealth.calendly_bookings`.

Once Calendly data is in BigQuery, use a view or RudderStack SQL to join Zoom events (by host + start time) to get **patient email** and send that to Klaviyo.

---

## Part 5 — Identity resolution (Zoom → patient email)

- Zoom sends **meeting_uuid**, **host_email**, **start_time**, **duration**; it does **not** send attendee email in the transcript webhook.
- Join Zoom events with Calendly data in BigQuery (e.g. match **host** + **start_time** ± a few minutes) to get **invitee email**.
- In RudderStack, either:
  - Use a **Transform** that calls BigQuery or an API to resolve `meeting_uuid` → email and set **userId** to that email before sending to Klaviyo, or  
  - Send Zoom events to BigQuery first; run a **Reverse ETL** or SQL-based sync that joins to Calendly and pushes the enriched event (with email) to Klaviyo.

Implement the join logic (e.g. in a BigQuery view or RudderStack SQL) and point Klaviyo at the resolved **userId** (email) so post-call flows target the right profile.

---

## Part 6 — Klaviyo (post-call flow)

1. In **Klaviyo**, create a **Metric** (or use an existing one) for the event name RudderStack sends: **Telehealth_Call_Finished**.
2. Create a **Flow** triggered by that metric.
3. Immediately after the trigger, add a **Conditional Split**:
   - Condition type: **What someone has done (or not done)**
   - Has done: `Telehealth_Call_Finished` where `productName` **equals** `No Show` — **at least once** — **in the last 2 hours**
   - **YES branch** → “We Missed You” email (for manual no-shows submitted via the form)
   - **NO branch** → existing product split (Liver / Cholesterol / Bundle) → post-call AI notes email
4. In each email, use the **event properties** (e.g. `kims_custom_note`, `meeting_date`, `productName`) as merge variables so the email is personalized.

> **Why this split:** The Google Form sends `Telehealth_Call_Finished` for both attended calls and manual no-shows, using `productName = “No Show”` and `attended = false` to distinguish them. A single flow with a split at the top handles all cases — no second flow needed.

---

## Part 6.5 — Google Form (No Show option)

The form uses a **Product/Program** dropdown. To enable the manual no-show path:

1. Open the Google Form.
2. In the **Product/Program** question, add **`No Show`** as a dropdown option (exact spelling: capital N, capital S, no punctuation).
3. In the Script Editor, paste the latest App Script from `scripts/google_form_to_rudderstack.js`.
4. When Kim selects **No Show**, only the **Email** field is required — notes and duration are optional. The backend bypasses duration checks and sends `Telehealth_Call_Finished` with `productName = "No Show"`.

---

## Part 7 — Test end-to-end

### 7.1 — Test Cloud Function (validation)

```bash
curl -X POST "YOUR_CLOUD_FUNCTION_URL" \
  -H "Content-Type: application/json" \
  -d '{"event":"endpoint.url_validation","payload":{"plainToken":"test123"}}'
```

Expected: JSON with `plainToken` and `encryptedToken`. If you get 400 or 500, check deployment and `ZOOM_SECRET_TOKEN`.

### 7.2 — Test with a real meeting

1. Schedule a **test** Calendly event (so you have an invitee email and start time in Calendly/BigQuery).
2. Join the Zoom meeting as host; enable **Cloud Recording** and **Audio transcript**.
3. Stay **> 5 minutes**; say clearly: “Summary for the email: Please send the patient a reminder to take their vitamins.”
4. End the meeting. The function receives `meeting.ended`, enqueues a poll; when the transcript is ready (~5–15 min) the poll downloads it and sends to RudderStack.
6. Check: Cloud Function logs (GCP Console → Cloud Functions → Logs), RudderStack event, BigQuery table, and Klaviyo (metric received, flow triggered, email contains `kims_custom_note`).

### 7.3 — If something fails

- **Zoom validation fails:** Correct Secret Token in Zoom app and in `ZOOM_SECRET_TOKEN`; redeploy function.  
- **No event in RudderStack:** Check `RUDDERSTACK_WEBHOOK_URL` and payload format; check function logs for “RudderStack delivery failed”.  
- **No transcript:** Ensure Cloud Recording and Audio transcript are on for the meeting; wait a few minutes after end.  
- **Flow not triggered:** Meeting must be **> 5 min** and transcript **> 50 words**; confirm event name and properties in Klaviyo.

---

## Quick checklist

| # | Step | Done |
|---|------|------|
| 1.1 | GCP project set | ☐ |
| 1.2 | APIs enabled | ☐ |
| 1.3 | Secrets created (Zoom, RudderStack, optional Gemini) | ☐ |
| 1.4 | Cloud Function deployed; URL copied | ☐ |
| 1.5 | Secret accessor IAM for function | ☐ |
| 2.1 | Zoom: Cloud Recording + Audio transcript on | ☐ |
| 2.2 | Zoom app (Event subscription) created | ☐ |
| 2.3 | Webhook URL = Function URL; subscribe to Transcript completed | ☐ |
| 2.4 | Zoom Secret Token in GCP secret | ☐ |
| 2.5 | Zoom app activated | ☐ |
| 3.1 | RudderStack HTTP/Webhook source created | ☐ |
| 3.2 | RudderStack URL + Write Key in GCP secrets | ☐ |
| 3.3 | BigQuery warehouse connected | ☐ |
| 3.4 | Klaviyo destination connected | ☐ |
| 4.1 | Calendly API token obtained | ☐ |
| 4.2 | Calendly → RudderStack or BigQuery | ☐ |
| 5 | Identity resolution (join Zoom + Calendly → email) | ☐ |
| 6 | Klaviyo flow for Telehealth_Call_Finished | ☐ |
| 6a | Klaviyo: Conditional Split — No Show (YES) → "We Missed You" email | ☐ |
| 6b | Google Form: "No Show" option added to Product/Program dropdown | ☐ |
| 6c | App Script updated (`scripts/google_form_to_rudderstack.js`) | ☐ |
| 7 | End-to-end test meeting | ☐ |

---

After this, the pipeline runs automatically: **Patient books (Calendly) → Meeting (Zoom) → Transcript completed → Cloud Function → RudderStack → BigQuery + Klaviyo** with `kims_custom_note` and meeting date in the event.
