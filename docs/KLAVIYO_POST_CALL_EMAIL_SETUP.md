# Klaviyo: Post-Call Email from Meeting Note — Step-by-Step

This guide walks you through setting up a Klaviyo flow that sends a follow-up email when a telehealth call finishes, using the meeting note (`kims_custom_note`) in the email content.

**Prerequisite:** RudderStack is connected to Klaviyo and receives the `Telehealth_Call_Finished` event. Events can come from (1) **Zoom** `meeting.ended` → Cloud Function → RudderStack (userId=meeting_uuid), or (2) **Google Form** → Cloud Function (verifies patient email, duration ≥ 5) → RudderStack with **userId=patient_email** so Klaviyo can send follow-up emails. For reliable delivery, use the form path (form POSTs to the same Telehealth webhook URL).

---

## Part 1 — Prerequisites

| # | Item | Status |
|---|------|--------|
| 1 | Zoom Cloud Function deployed and sending events to RudderStack | ☐ |
| 2 | RudderStack HTTP source receiving `Telehealth_Call_Finished` | ☐ |
| 3 | RudderStack → Klaviyo destination connected | ☐ |
| 4 | For email delivery: use **form path** (userId=patient_email) or resolve Zoom meeting_uuid → email (Part 5) | ☐ |

**Event shape** (from `main.py`): RudderStack sends a track event with:

- **Event name:** `Telehealth_Call_Finished`
- **userId:** **Form path:** patient email (from form). **Zoom path:** meeting_uuid (no email; use form or identity resolution for delivery).
- **properties:** **`email`**, **`name`** (form path; Zoom path has no person email on the event), `kims_custom_note` (newline-separated `•` lines — use **`|linebreaksbr`** in HTML emails), `duration`, `meeting_date`, `host_email` (if tied to Zoom), `source` (`google_form` or `zoom_meeting_ended`), `attended`, and optionally **`productName`** / **`Product`** for flow splits. Incoming JSON can still use `patient_email` / `patient_name`; those are **not** duplicated on the outbound event.

---

## Part 2 — Create the Metric in Klaviyo

1. Log in to **Klaviyo**.
2. Go to **Analytics** → **Metrics**.
3. Search for **Telehealth_Call_Finished**.
   - If it already exists (events have been sent), skip to Part 3.
   - If it does not exist, it will be **created automatically** when the first event is received from RudderStack. You can also create a **Custom Metric** and set the metric name to **Telehealth_Call_Finished** so it’s ready.

### Why don’t I see Telehealth_Call_Finished in the trigger list?

**Klaviyo only shows a metric in the flow trigger list after at least one event with that name has been received.** If you haven’t sent a test event yet, the metric won’t appear under “Your metrics.”

**Option A — Send a test event first (recommended)**  
1. Run one end-to-end test: Zoom meeting (5+ min, use the test script in `docs/ZOOM_TEST_SCRIPT.md`) so the Cloud Function sends a `Telehealth_Call_Finished` event to RudderStack and RudderStack forwards it to Klaviyo.  
2. In Klaviyo, go to **Analytics** → **Metrics** and confirm **Telehealth_Call_Finished** appears.  
3. Then go to **Flows** → **Create Flow** → **Select a trigger**. Under **Your metrics**, **Telehealth_Call_Finished** should now be in the list; select it and continue.

**Option B — Check under “API”**  
If your events are sent via RudderStack (HTTP/API), the metric may be grouped under **API** in the trigger list. In **Select a trigger**, look for **API** in the list, click it, and see if **Telehealth_Call_Finished** (or your track event name) appears as a metric you can select.

**Option C — Create the metric so it’s ready**  
Some Klaviyo accounts let you create a **Custom Metric** with a specific name. If available: **Analytics** → **Metrics** → create custom metric named **Telehealth_Call_Finished**. Then when building the flow, look for that metric under **Your metrics** or **All triggers**. Not all plans support this; if you don’t see it, use Option A.

---

## Part 3 — Create the Flow

1. Go to **Flows** → **Create Flow**.
2. Choose **Create from scratch**.
3. **Trigger:**
   - Under **Select a trigger**, open **Your metrics** (or **API** if your event comes from the API).
   - Select **Telehealth_Call_Finished**. *(If it’s not there, send one test event first — see “Why don’t I see Telehealth_Call_Finished?” above.)*
4. **Trigger filter (avoid no-shows):** Add a filter so the flow only runs when the call lasted 5+ minutes:
   - After selecting the trigger, click **Add filter** (or **Set trigger filter**).
   - Add condition: **Event property** → `duration` → **is at least** → `5`.
   - This ensures emails are sent only when the call actually happened and lasted 5+ min (matches Zoom and Google Form pipelines).
   - **Important:** Do **not** add a filter on **Event property** → `source` → **equals** → `zoom_meeting_ended` if you use the **Google Form** path. Form submissions send `source: "google_form"`; filtering only on Zoom would cause every form submission to be **skipped** (flow shows “X skips”).
5. Click **Create Flow** (or **Next**).
6. Name the flow (e.g. **Post-Call Follow-Up Email**).

---

## Part 4 — Add the Email and Use Meeting Note

1. In the flow canvas, click **+** to add a step.
2. Select **Send Email**.
3. Create a new email or choose an existing template.

### Email content

- **Subject:** e.g. `Follow-up from your consultation` or use a merge variable.
- **Body:** Use Klaviyo’s **merge variables** so the meeting note appears in the email.

### Merge variables (event properties)

| Property from event | Klaviyo merge variable | Description |
|--------------------|------------------------|-------------|
| Meeting note       | `{{ event.kims_custom_note\|linebreaksbr }}` | Klaviyo does **not** support `nl2br` (that causes **Email Syntax Error**). Use Django filter **`linebreaksbr`** (alias: `newline_to_br`). Requires an **HTML** email block. |
| Meeting date       | `{{ event.meeting_date }}`     | Date/time of the call |
| Sentiment          | `{{ event.sentiment }}`        | Optional |
| Internal summary   | `{{ event.internal_summary }}` | Optional (internal use) |
| Product (for splits)| `{{ event.productName }}`             | Optional; add form field and map to `product_name` or `productName` so flow splits (e.g. productName contains Liver / Cholesterol / Bundle) route correctly. |

### Flow splits (e.g. Liver / Cholesterol / Bundle)

The flow is **event-based**: it is triggered by the form submission, and conditional splits use **event properties**. If you add splits on `productName` (e.g. "productName contains Liver"), the Google Form must include a product field and the webhook must receive it. We send it as `productName` when the form includes `product_name` or `productName`. Without it, every submission goes to the "All Else" branch.

### Example email block

```
Hi {{ person.first_name|default:"there" }},

Thank you for your recent consultation. Based on our discussion:

{{ event.kims_custom_note|linebreaksbr }}

If you have any questions, feel free to reply to this email.
```

4. Save the email and connect it in the flow (e.g. immediately after the trigger, or after a delay if you want a wait step).
5. **Save** the flow and **Turn on** the flow when ready.

---

## Part 5 — Identity Resolution (userId = Patient Email)

Klaviyo sends the email to the **profile** identified by the event’s **userId**. If **userId** is the Zoom `meeting_uuid`, Klaviyo will not match a profile by email and the email may not send or may go to the wrong profile.

**Form path:** We send `userId: patient_email`. For the flow to deliver, that email must exist as a **Klaviyo profile** (or Klaviyo must create one from the event). If the profile doesn’t exist and your account doesn’t create profiles from API events, the flow can **skip** (e.g. “7 skips” in flow stats). Fix: ensure the test patient email is in Klaviyo (e.g. add to a list, or send a test event first so the profile is created).

**Current behavior:** `main.py` sends `"userId": meeting_uuid` to RudderStack. Zoom does not include patient email in the transcript webhook.

**What you need:** Before (or when) events reach Klaviyo, **userId** should be the **patient email** (or a stable external ID that Klaviyo can match to a profile with email).

**Ways to resolve identity:**

1. **RudderStack Transform:** In RudderStack, add a transform that:
   - Joins the event to BigQuery (or an API) using `meeting_uuid`, `host_email`, and `meeting_date` (or `start_time`) to get the Calendly **invitee email**.
   - Overwrites **userId** with that email before sending to Klaviyo.

2. **BigQuery + Reverse ETL:** Persist Zoom events to BigQuery; run a job (RudderStack Reverse ETL or Cloud Function) that joins Zoom events to `telehealth.calendly_bookings` (host + start time) to get invitee email, then send an enriched event to Klaviyo with **userId** = email.

3. **Update Cloud Function:** If you can resolve email in the Cloud Function (e.g. by calling BigQuery to look up Calendly by host + meeting start time), then send **userId** = email in the RudderStack payload instead of `meeting_uuid`.

Until **userId** is the patient email (or a Klaviyo-known identifier), the flow will trigger but may not deliver to the right person. Document your chosen approach in `docs/SETUP_STEP_BY_STEP.md` Part 5.

---

## Part 6 — Test End-to-End

1. **Schedule a test Calendly booking** (so Calendly/BigQuery has the invitee email).
2. **Run a Zoom meeting** (Cloud Recording + Audio transcript on, duration > 5 min). Say clearly: *“Summary for the email: [your test note].”*
3. **Wait** for the poll to find the transcript (~5–15 min after the call ends).
4. **Verify:**
   - **Klaviyo** → **Analytics** → **Metrics** → **Telehealth_Call_Finished**: event appears.
   - Open the **profile** (matched by userId/email): activity shows the event and properties (`kims_custom_note`, etc.).
   - **Flow** runs and the **email** is sent to the correct address with the meeting note in the body.

---

## Part 7 — Get notified when the follow-up email is sent (Slack)

You can get a Slack message each time the post-call follow-up email is sent by adding a **Webhook** action after the "Send Email" step in your Klaviyo flow. This project includes a small Cloud Function that receives that webhook and posts to Slack.

### 7.1 Deploy the callback function

1. Set your Slack webhook URL (can be the same as the 15-min reminder or a different channel):
   ```bash
   export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
   ```
2. Optional: set a shared secret so only Klaviyo can call the endpoint (recommended if the URL is public):
   ```bash
   export KLAVIYO_CALLBACK_SECRET="your-random-secret"
   ```
3. Deploy the function:
   ```bash
   ./scripts/deploy_klaviyo_email_sent.sh
   ```
4. Note the **Callback URL** printed at the end (e.g. `https://klaviyo-email-sent-handler-xxxx.run.app`). You will paste this into Klaviyo in the next step.

#### If deploy fails: organization policy / “permitted customer”

Some GCP organizations block **`allUsers`** (public) as **Cloud Run Invoker**. `gcloud functions deploy ... --allow-unauthenticated` then fails with an error like: *One or more users named in the policy do not belong to a permitted customer, perhaps due to an organization policy.*

**What still worked:** Your **Calendly reminder** deploy is separate; only this Klaviyo callback needs a public HTTPS POST from Klaviyo’s servers.

**Options:**

1. **Admin / policy:** Ask a GCP org admin to allow unauthenticated invoke for **`klaviyo-email-sent-handler`** (or the underlying Cloud Run service) in your project, then redeploy with the default script (public invoke).
2. **Deploy without public IAM, then adjust in Console:** If policy blocks the CLI but Console can add invoker for your role:
   ```bash
   KLAVIYO_DEPLOY_NO_PUBLIC_IAM=1 ./scripts/deploy_klaviyo_email_sent.sh
   ```
   Then in **Google Cloud Console** → **Cloud Run** → open the service for `klaviyo_email_sent_handler` → **Security** → enable **Allow unauthenticated invocations** if your org allows it. If that toggle is blocked, you need option 1 or a small public relay outside the org (not included here).
3. **Redeploy from Cloud Console:** Create or update the Gen2 function there and map **`SLACK_WEBHOOK_URL`** from secret **`SLACK_WEBHOOK_URL_TELEHEALTH:latest`** (same pattern as `calendly_reminder_handler`).

### 7.2 Add the Webhook action in Klaviyo

1. In **Klaviyo** → **Flows** → open your **Telehealth Post-Call Follow-Up** flow.
2. Click **+** after the **Send Email** step and add a **Webhook** action.
3. **URL:** Paste the callback URL from step 7.1. It must be HTTPS.
4. **Headers (optional):** If you set `KLAVIYO_CALLBACK_SECRET`, click **+ Add Headers** and add:
   - **Key:** `X-Klaviyo-Callback-Secret`
   - **Value:** the same secret value you set in the deploy.
5. **Body:** Use a JSON payload so the function can post a clear message to Slack. Click **View profile and event variables** to see available variables, then set the body to:
   ```json
   {
     "email": "{{ person.email }}",
     "name": "{{ event.name }}"
   }
   ```
   (`event.name` is the display name on the metric; `patient_name` is no longer sent on the event. You can omit `name` if you only need Slack to show the email; the function accepts `name` or legacy `patient_name`.)
6. Click **Save**. Klaviyo will validate the webhook; if it fails, check the URL and that the function is deployed with `allow-unauthenticated` (so Klaviyo's servers can POST).
7. **Save** the flow and keep it **Turned on**.

After this, whenever the flow sends the follow-up email, Klaviyo will POST to your callback and you'll see a Slack message like: *"Follow-up email sent to Jane Doe (jane@example.com)"*.

### 7.3 Webhook after every split or one webhook?

- If **each product branch** (Liver / Cholesterol / Bundle) has its **own “Send Email”** step and you want a **Slack ping for every branch**, add a **Live** webhook **immediately after each** of those emails (same URL and body pattern on each). Profiles only travel down **one** branch, so only that branch’s webhook runs.
- If you only need **one** follow-up email design for everyone, you can **merge branches** earlier and use **one** email + **one** webhook (less duplication).
- Putting **one** webhook **before** the split would run **before** any branch-specific email and would **not** mean “email sent” for a given template; prefer the webhook **after** the email that should trigger the notification.

### Other options (if you don't use the flow webhook)

If you prefer not to use the flow webhook action, you have a few alternatives:

| Option | What you need | How it works |
|--------|----------------|---------------|
| **Klaviyo webhooks (Advanced KDP)** | Klaviyo account with [Advanced KDP](https://developers.klaviyo.com/en/reference/webhooks_api_overview) (webhooks add-on). | Create a webhook for “Received Email” (or “Sent Email”) and set the URL to a small Cloud Function that receives the payload and posts to your Slack webhook (e.g. “Follow-up email sent to customer@example.com”). |
| **Klaviyo Flow + action** | Check Klaviyo flow editor for your plan. | Some plans let you add an action after “Send Email” (e.g. “Trigger webhook” or “HTTP request”) that calls your endpoint with the recipient email or event id; your endpoint then posts to Slack. |
| **Poll Klaviyo Metrics API** | Klaviyo API key, scheduled job (e.g. Cloud Scheduler + Cloud Function). | Every 5–10 min, call the [Metrics API](https://developers.klaviyo.com/en/reference/get_metric_events) or profile timeline for the “Received Email” (or “Sent Email”) metric filtered by your flow/campaign. For new events, post “Follow-up sent to &lt;email&gt;” to Slack. More work to build and maintain. |

**Practical choice:** If you have Advanced KDP, use Klaviyo webhooks → Cloud Function → Slack. Otherwise, use the flow’s analytics in Klaviyo (Delivered count) for confirmation, or explore whether your flow can trigger an HTTP callback after the email step.

---

## Quick Checklist

| # | Step | Done |
|---|------|------|
| 1 | RudderStack → Klaviyo connection configured | ☐ |
| 2 | Identity: userId = patient email (Part 5) | ☐ |
| 3 | Metric **Telehealth_Call_Finished** exists in Klaviyo | ☐ |
| 4 | Flow created; trigger = **Telehealth_Call_Finished** | ☐ |
| 5 | Email uses `{{ event.kims_custom_note|linebreaksbr }}` (and optional event vars) | ☐ |
| 6 | Flow turned on | ☐ |
| 7 | End-to-end test: meeting → event → email received | ☐ |
| 8 | (Optional) Slack notification when email is sent: deploy `klaviyo_email_sent` and add Webhook after Send Email (Part 7) | ☐ |

---

## Related docs

- **Zoom + Cloud Function + RudderStack:** `docs/SETUP_STEP_BY_STEP.md` (Parts 1–3, 7).
- **Identity resolution (Zoom → email):** `docs/SETUP_STEP_BY_STEP.md` Part 5.
- **Event payload and pipeline:** `docs/TELEHEALTH_WORKFLOW_PLAN.md`, `main.py`.
