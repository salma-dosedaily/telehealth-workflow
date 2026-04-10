# Troubleshooting: Calendly webhook & RudderStack 0 events

## Calendly webhook: no events, container crash, main.py / genai in logs

### What went wrong

If Cloud Run logs for **calendly-webhook-handler** show:

- `File "/workspace/main.py"` and `import google.generativeai as genai`
- **Traceback** in `functions-framework`, **Container called exit(1)**
- **STARTUP TCP probe failed** (e.g. on port 8888) and **Ready condition status changed to False**

then the Calendly service was deployed from the **repo root** (`--source=.`). That uploads **main.py** (Zoom + Gemini) as well. Loading Zoom’s code in the Calendly container causes the deprecation warning and can crash the service, so it never stays healthy and **Calendly events are never received**.

### Fix: deploy Calendly from `functions/calendly` only

Deploy the Calendly webhook **only** from the `functions/calendly` directory (no `main.py`, no `genai`):

```bash
cd /path/to/telehealth-workflow
./scripts/deploy_calendly_webhook.sh
```

Or manually:

```bash
gcloud functions deploy calendly_webhook_handler \
  --gen2 --runtime=python312 --region=us-central1 \
  --source=functions/calendly \
  --entry-point=calendly_webhook_handler \
  --trigger-http --allow-unauthenticated \
  --set-secrets=CALENDLY_PERSONAL_ACCESS_TOKEN=CALENDLY_PERSONAL_ACCESS_TOKEN:latest \
  --set-env-vars=GCP_PROJECT=dosedaily-raw \
  --project=dosedaily-raw
```

After deploy:

1. In Cloud Run, confirm **calendly-webhook-handler** is **Ready** and logs no longer show `main.py` or `genai`.
2. Re-register the webhook with Calendly (same URL or new one from the deploy output):
   ```bash
   python scripts/register_calendly_webhook.py --url "https://calendly-webhook-handler-XXXX.run.app"
   ```
3. Create a **new test event** in Calendly and confirm a row in `dosedaily-raw.telehealth.calendly_bookings`.

---

## RudderStack: 0 events for “Telehealth Zoom Webhook”

### Why you might see 0 events

The Zoom Cloud Function sends to RudderStack **only** when **all** of the following are true:

1. Zoom sends the event **meeting.ended** (not just “meeting ended”).
2. Zoom’s Event subscription URL is correct and the function is public.
3. Request passes **signature verification** (correct `ZOOM_SECRET_TOKEN`).
4. Meeting **duration ≥ 5 minutes**.
5. Transcript is available and **download** succeeds.
6. Transcript **word count ≥ 50** (no-show check).
7. **POST to RudderStack** succeeds (correct `RUDDERSTACK_URL` and `RUDDERSTACK_WRITE_KEY`).

If any step fails, the function returns without sending a track event (e.g. “Event ignored”, “Meeting duration < 5 min”, “No-show detected”, “RudderStack delivery failed”), so RudderStack shows **0 ingested events**.

### Checklist

| Step | What to check |
|------|----------------|
| 1 | Zoom App → Event subscription → subscribed to **Meeting → Meeting ended** (`meeting.ended`); Zoom API auth configured for poll (see ZOOM_FAST_PATH_SETUP.md). |
| 2 | Event notification endpoint URL = your Zoom Cloud Function URL (e.g. `telehealth-webhook-handler-...run.app` or `...cloudfunctions.net/telehealth_webhook_handler`). |
| 3 | Zoom **Secret Token** matches the value in GCP Secret Manager `ZOOM_SECRET_TOKEN`. |
| 4 | Test meeting: **Cloud Recording** and **Audio transcript** on; meeting length **> 5 min**; say enough so transcript is **≥ 50 words** (e.g. use `docs/ZOOM_TEST_SCRIPT.md`). |
| 5 | In GCP, Cloud Function logs: look for “RudderStack delivery failed” (wrong URL/key) or “Success” (event sent). |
| 6 | RudderStack source “Telehealth Zoom Webhook”: **Write key** and **Data plane URL** match what the function uses (`RUDDERSTACK_WRITE_KEY`, `RUDDERSTACK_URL`). |

### Quick test

1. Run a **single** Zoom test that meets all criteria (5+ min, transcript, 50+ words).
2. Wait ~5–15 min for the poll to find the transcript (Zoom must have Cloud Recording + Audio transcript on).
3. Check **Cloud Run/Cloud Functions** logs for `telehealth-webhook-handler`: you should see an invocation and no “RudderStack delivery failed”.
4. In RudderStack, wait up to ~2 minutes; “Events Ingested” for the source should increase.

If logs show "Success" but RudderStack still shows 0, the problem is between the function and RudderStack (URL, write key, or destination configuration).

### Zoom: Webhook Logs show “No data” — Zoom never hit the API

If Zoom’s **Webhook Logs** (or **API Call Logs**) for your app show **“No data”**, Zoom has **not sent any webhook requests** to your endpoint. The problem is in the Zoom app configuration, not in your Cloud Function.

**Do this in order:**

1. **Event subscription is on**
   - In Zoom Marketplace → **Develop** → **Created apps** → **Telehealth Automation**.
   - Go to **Event subscription** (or **Features** → **Event subscription**).
   - Ensure **Event subscription** is **Enabled** (toggle on).

2. **Endpoint URL is set and correct**
   - In the same **Event subscription** section, find **Event notification endpoint URL**.
   - Set it to your Cloud Function URL **exactly** (no trailing slash), e.g.:
     - `https://telehealth-webhook-handler-XXXXX-uc.a.run.app`  
     - or `https://us-central1-dosedaily-raw.cloudfunctions.net/telehealth_webhook_handler`
   - Get the live URL with:
     ```bash
     gcloud functions describe telehealth_webhook_handler --gen2 --region=us-central1 --project=dosedaily-raw --format='value(serviceConfig.uri)'
     ```

3. **Validate the endpoint**
   - In Event subscription, click **Validate** (or **Add** then **Validate**).
   - Zoom sends a test request (`endpoint.url_validation`). If validation succeeds, the URL is accepted.
   - If it fails: the URL must be publicly reachable (Cloud Run → **Security** → **Allow public access** for that service), and your function must return the expected JSON for the validation payload.

4. **Subscribed to the right events**
   - Under **Subscribe to events**, add at least:
     - **Meeting** → **Meeting ended** (`meeting.ended`) — required for the pipeline.
     -    - If you only subscribe to “Meeting ended”, you will **not** get transcript events; the log may still stay empty until a transcript is ready (and then only for `meeting.ended` if that’s added).

5. **App is activated**
   - The app must be **Activated** for the Zoom account that **hosts** the meetings. If the app is in development or not activated, Zoom will not send webhooks.

6. **Trigger a real event**
   - Webhook Logs may stay “No data” until the first event is sent. Run a **test meeting** (same account as the app):
     - Start **Cloud Recording** and **Audio transcript**.
     - Stay **5+ minutes**, say **50+ words** (e.g. read `docs/ZOOM_TEST_SCRIPT.md`).
     - End the meeting. The function receives `meeting.ended` and enqueues a poll; when Zoom has the transcript (~5–15 min) the poll finds it and runs the pipeline.
   - After that, check Webhook Logs again; you should see a row (and your Cloud Run logs should show a POST).

If after **Validate** you still see “No data”, check **Legacy Webhook Logs** in the same app; some Zoom UIs show delivery attempts there. Also confirm in **GCP Logging** (Cloud Run → telehealth-webhook-handler → Logs) that no POST from Zoom appears; if **Validate** worked, you should see at least one POST for the validation request.

---

### Zoom: No logs at all — webhook never received

If **no** POST requests appear in Cloud Run logs for `telehealth-webhook-handler`, Zoom is not calling your function. Work through this list:

**1. Confirm your Cloud Function URL**

You can have either (both point to the same function):

- `https://telehealth-webhook-handler-pshv76iija-uc.a.run.app`
- `https://us-central1-dosedaily-raw.cloudfunctions.net/telehealth_webhook_handler`

In **Zoom Developer** → **Your app** → **Event subscription**, the **Event notification endpoint URL** must be **exactly** one of these (no trailing slash unless you’re sure Zoom sends it).

**2. Test that the URL is reachable**

From your machine (replace `YOUR_ZOOM_SECRET` with the Secret Token from Zoom):

```bash
curl -X POST "https://telehealth-webhook-handler-pshv76iija-uc.a.run.app" \
  -H "Content-Type: application/json" \
  -d '{"event":"endpoint.url_validation","payload":{"plainToken":"test123"}}'
```

You should get back JSON with `plainToken` and `encryptedToken`. If you get 401, the Secret Token in Zoom and in GCP Secret Manager `ZOOM_SECRET_TOKEN` must match. If you get 400/404, the URL or path is wrong.

**3. Zoom App configuration**

- **Feature** → **Event subscription** → **Enabled**.
- **Subscribe to events:** must include **Meeting** → **Meeting ended** (`meeting.ended`). If you only have “Meeting ended” or similar, the transcript event will never be sent.
- Click **Validate** (or re-validate) so Zoom sends a test and shows the endpoint as valid.
- **Activation:** app must be **activated** for the account that hosted the meeting.

**4. Meeting had Cloud Recording + Audio transcript**

- Zoom **Admin** (or **Settings**) → **Recording** → **Cloud recording** and **Audio transcript** enabled.
- The specific meeting must have been recorded (start Cloud Recording during the meeting).

**5. Redeploy and wait**

After any code change (e.g. the new “Zoom webhook received” log), redeploy so the latest code is live:

```bash
./scripts/deploy_zoom_webhook.sh
```

Then run another test meeting (10+ min, Cloud Recording on, say the test script). Shortly after ending, you should see `Zoom webhook received: event='meeting.ended'` and `Meeting.ended: poll enqueued`. Within ~5–15 min the poll will find the transcript and run the pipeline.

---

### Zoom: "Call was 10+ minutes but no logs appeared" / "Transcript webhook taking forever"

**Transcript delay (Zoom-side, not fixable in our code):** The poll checks Zoom every 2 min. Zoom typically has the transcript ready 5–15 min after the meeting ends; sometimes up to ~40 min. There is **no fixed SLA** from Zoom:

- **Typical:** 5–15 minutes after the meeting ends.
- **Common:** 15–45 minutes; **25+ minutes is normal** and does not mean anything is broken.
- **Reported:** Some users see **30–60+ minutes** or even **hours** (e.g. [Zoom Developer Forum: 2-hour delay](https://devforum.zoom.us/t/2-hour-delay-on-phone-recording-transcript-completed/121239), [transcription completion time](https://devforum.zoom.us/t/transcription-completion-time/39368)).

So **wait at least 15–30 minutes** after the call ends before assuming the webhook failed. If after **45–60 minutes** you still see no POST in Cloud Run logs, then treat it as a delivery/configuration issue and follow the "Zoom: No logs at all" checklist below.

**If you need faster delivery:** Zoom does not offer a way to speed up transcript processing. A possible future improvement is to subscribe to `meeting.ended`, then poll Zoom’s REST API (e.g. [List recording files](https://developers.zoom.us/docs/api/rest/reference/zoom-api/meetings/meetingrecordings/)) until a `TRANSCRIPT` file appears, then run the same pipeline—this is not implemented today.

**Check that Zoom is calling your function:**
1. In **GCP Console** → **Logging** (or Cloud Run → telehealth-webhook-handler → Logs), filter by **Request** or `httpRequest.requestMethod="POST"`.  
2. Look for **POST** requests in the last 1–2 hours.  
   - **No POSTs:** Zoom isn’t sending to this URL, or the event isn’t `meeting.ended` (e.g. only `meeting.ended`). Fix: Zoom App → Event subscription → subscribe to **Meeting → Meeting ended**; endpoint URL = your Cloud Function URL.  
   - **POST 200:** Check the log line: you should see either `Event ignored: event='...'` (wrong event type), or one of the other messages (no transcript, duration, no-show, or Success).  

**Check Zoom side:**
- Meeting had **Cloud Recording** and **Audio transcript** enabled (account or per meeting).
- Zoom App is **activated** and Event subscription **Validated**.
- In Zoom Developer → Your app → **Webhook** (or Event subscription): confirm the **Event notification endpoint URL** is exactly your function URL.

### Why you see only GET 400 / GET 404 in the Zoom function logs

Those are **browser requests** (Chrome opening the URL or favicon). They are expected: the handler returns 400 for non-POST and 404 for `/favicon.ico`. They are **not** Zoom webhook calls. Zoom sends **POST** with JSON. Check for **POST** requests in the same logs; if there are no POSTs, Zoom is not calling this URL or no `meeting.ended` event has fired yet.

### Confirmed: RudderStack has 0 events for Telehealth Zoom Webhook

If you use RudderStack MCP, you can confirm with `get_source_event_metrics` for source "Telehealth Zoom Webhook": **eventCount** will be 0 until at least one event is received. The Zoom function only sends an event when the poll finds the transcript and passes duration + no-show checks.

---

## Firestore: "The database (default) does not exist"

**Symptom:** Cloud Function logs show:
`Failed to store meeting_ended: 404 The database (default) does not exist for project ... Please visit https://console.cloud.google.com/datastore/setup?project=... to add a Cloud Datastore or Cloud Firestore database.`

**Cause:** The Firestore API is enabled but the **Firestore database** was never created. Enabling the API is not enough; you must create the (default) database once per project.

**Fix (pick one):**

1. **Run the setup script** (it now creates the database if missing):
   ```bash
   ./scripts/setup_firestore_form_secret.sh
   ```
   If the script exits with "Create the Firestore database manually", use option 2.

2. **Create the database in the Console:**
   - Open: [Datastore / Firestore setup](https://console.cloud.google.com/datastore/setup?project=dosedaily-raw) (replace `dosedaily-raw` with your project ID).
   - Choose **Firestore Native mode** (not Datastore mode).
   - Pick a location (e.g. **us-central1** to match your Cloud Function).
   - Click **Create database**. After it’s created, end another call and submit the form again; storage and lookup will work.

3. **Create via gcloud** (if your `gcloud` supports it):
   ```bash
   gcloud firestore databases create --location=us-central1 --project=dosedaily-raw
   ```

**host_email is null in Firestore:** Zoom’s meeting.ended payload often includes `host_id` but not `host_email`. The webhook now calls Zoom’s GET /users/{host_id} to resolve the host’s email. If host_email is still null, the Zoom app may lack a scope that allows reading the user (e.g. **user:read** or **user:read:admin**). Add that scope to the Zoom app and re-authorize (e.g. re-run the OAuth flow) so the token has permission.

**If you already created a *named* database** (e.g. **telemeetinglog**) instead of the default: the function looks for the database named `(default)` by default. Either create the `(default)` database as above, or point the function at your named database by setting **FIRESTORE_DATABASE_ID** and redeploying:
   ```bash
   FIRESTORE_DATABASE_ID=telemeetinglog ./scripts/deploy_zoom_webhook.sh
   ```
   Then end a call and submit the form again; meeting_ended will be stored in `telemeetinglog` and form lookup will work.

No code or redeploy needed for (default); for a named DB, set `FIRESTORE_DATABASE_ID` and redeploy.

---

## Google Form: Patient email not prefilling when pasting meeting link

**Expected behavior:** Pasting the Zoom meeting link into the “Meeting UUID” field does **not** fill the “Patient Email” field. That is by design.

**Why:** Google Forms has no built-in way to “when this field changes, look up and fill that field.” The Zoom join URL also does **not** contain the patient’s email (it only has meeting ID and optional password). So the form script cannot derive or prefill patient email from the meeting link.

**How to get Patient Email prefilled:**

1. Use a **prefilled form link** so the patient (or Kim) opens the form with the email already filled.
2. In the form editor: **Responses** → **⋮** → **Get pre-filled link**.
3. Fill in **Patient Email** (and any other fields you want), then submit. Google shows a URL like:
   `https://docs.google.com/forms/d/FORM_ID/viewform?entry.123456789=patient@example.com`
4. Use that URL when sending the form to the patient or when Kim opens it for that patient. When they open it, the Patient Email field will already show that value. They can then paste the meeting link into “Meeting UUID” and fill the rest.

**Optional:** Save the form’s entry IDs (from the prefilled URL) and build links in a spreadsheet or script: `FORM_URL + "?entry." + ENTRY_ID_EMAIL + "=" + encodeURIComponent(email)`.

---

## Klaviyo: Duplicate profiles (same email, one from form / one from Calendly or other source)

**Symptom:** Two Klaviyo profiles for the same email. One often has **External ID** equal to the **email** (from the Google Form → Cloud Function path, which sends `userId` = normalized email). The other has a **different External ID** (numeric or opaque string) from another RudderStack source that uses its own ID as `userId`.

**Why code alone may not fix it:** `main.py` and the form script already normalize email and send `identify` + `track` with consistent `userId`. The split happens when **another integration** sends the same person with a **different `userId`** to the same Klaviyo destination. RudderStack’s default Klaviyo mapping uses **`userId` → Klaviyo external_id**, so different `userId`s → different profiles.

**Fix:**

1. In **RudderStack** → **Destinations** → your **Klaviyo** destination → connection settings, turn **ON** **“Use email or phone as primary identifier”** (or **“Enable this option to make email or phone as primary identifier”** — exact label varies by destination version). Per RudderStack docs, this uses **`traits.email` / `properties.email`** as the primary merge signal and avoids anchoring the profile only to conflicting `userId` values.
2. In **Klaviyo** → **Audience** → **Profiles**, **merge** the duplicate profiles for affected emails (one-time cleanup).
3. Confirm **all** RudderStack sources that feed that Klaviyo destination include a reliable **`email`** on identify/track where possible.

Reference: [RudderStack — Klaviyo setup guide](https://www.rudderstack.com/docs/destinations/streaming-destinations/klaviyo/setup-guide/).

---

## Klaviyo: RudderStack events succeed but flow shows “X skips” and no email is sent

**Symptom:** RudderStack shows the `Telehealth_Call_Finished` events as successful, but in Klaviyo the flow shows **skips** (e.g. “7 skips”) and the follow-up email is never sent.

**Common causes and fixes:**

| Cause | What to check | Fix |
|-------|----------------|-----|
| **Trigger filter on `source`** | Flow trigger has a filter like “Event property `source` equals `zoom_meeting_ended`”. | Form submissions send `source: "google_form"`. Remove the `source` filter, or add an OR: `source` equals `zoom_meeting_ended` **or** `source` equals `google_form`. See **Part 3** in `docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md`. |
| **Profile not found (userId)** | We send `userId: patient_email`. Klaviyo sends the email to the profile with that identifier. | Ensure the test patient email exists as a Klaviyo profile (e.g. add to a list, or send one event first so the profile is created). If “Create profile from API” (or similar) is off and the email isn’t in Klaviyo, the flow can skip. See **Part 5** in `docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md`. |
| **Duration filter** | Trigger filter “Event property `duration` is at least 5”. | We send `duration` as a number (e.g. 10). If the filter is correct, this should pass. If you added a typo or wrong property name, fix the trigger filter. |
| **Flow not turned on** | Flow is in draft or paused. | In Klaviyo → Flows → open the flow → **Turn on** (or **Activate**). |

**Quick checklist:** (1) Trigger = `Telehealth_Call_Finished`, filter only `duration` ≥ 5 (no `source` filter, or include `google_form`). (2) Test with a patient email that already has a Klaviyo profile. (3) Flow is turned on. (4) In Klaviyo **Analytics** → **Metrics** → **Telehealth_Call_Finished**, open an event and confirm `userId` and `source` match what you expect.

**If the flow shows "Skipped: 7" and Delivered: 0:** Click the **Trigger** block → **Trigger filter**. Remove any condition that filters on **Event property** `source` (or add an OR so `source` equals `google_form` is allowed). Form submissions send `source: "google_form"`. Then click **Email #1** → ensure there is no filter that would exclude these profiles (e.g. "Person is in list" when the test email isn’t in that list). Finally, in **Audience** → **Profiles**, search for the exact patient email you used; if no profile exists, Klaviyo may skip. Create the profile (e.g. by adding that email to a list or sending one test event) and resubmit the form.

### "Skipped: Missing Email" — identify is sent before track

The Cloud Function sends a RudderStack **identify** (with `userId` and `traits.email`) before each **track** so the Klaviyo profile has an email. If you still see "Skipped: Missing Email":

- **RudderStack → Klaviyo:** In RudderStack, ensure the Klaviyo destination is configured to **accept Identify calls** and to map `traits.email` (or the identifier) to Klaviyo’s email field. Some destinations require "Create profiles from server-side events" or similar.
- **Order:** Identify is sent first, then track. If Klaviyo still skips, check RudderStack’s event order or add a short delay before the email step in the flow so the identify is applied before the send.

### Step-by-step: "I still receive no email from Klaviyo"

1. **Confirm the event reaches Klaviyo**  
   Klaviyo → **Analytics** → **Metrics** → **Telehealth_Call_Finished**. Do you see the event for the test submission? If **no**, the issue is before Klaviyo (Cloud Function → RudderStack → destination). Check Cloud Run logs for "Success: Telehealth_Call_Finished" and "RudderStack identify sent"; check RudderStack for events and Klaviyo destination delivery.

2. **Confirm the profile has an email**  
   Klaviyo → **Audience** → **Profiles** → search for the **exact** patient email you used. Open the profile. Does it show an **Email**? If **no**, the identify didn’t create/update the profile with email — fix RudderStack identify mapping or create the profile manually (e.g. add to a list) and test again.

3. **Check why the flow skipped**  
   Klaviyo → **Flows** → open your post-call flow → **Analytics** (or the trigger/email block). Note the **Triggered** vs **Skipped** count. Click the trigger → **Trigger filter**: remove any filter on `source` or allow `source` = `google_form`. Click the **Email** step → **Filter**: remove conditions that would exclude the test profile (e.g. "Person is in list X" when that email isn’t in the list).

4. **Flow is on**  
   The flow must be **Turned on** (not draft/paused).

5. **Re-test**  
   Submit the form again with the same patient email; wait 1–2 minutes and check Metrics + profile + flow stats.

---

## Calendly webhook: GET 403 Forbidden

If logs for **calendly-webhook-handler** show **GET 403** when you (or Calendly) hit the URL, the service is **rejecting the request before it reaches your code**—usually because **invoker access** is not public.

### Fix: allow unauthenticated invocations

1. In **Google Cloud Console** → **Cloud Run** → open **calendly-webhook-handler**.
2. Go to the **Security** tab (or **Permissions**).
3. Under **Authentication**, select **Allow public access** (or add principal `allUsers` with role **Cloud Run Invoker**).
4. Save. Then re-test: Calendly’s POSTs (and your browser GET) should get through; your handler still returns 405 for GET, which is correct.
