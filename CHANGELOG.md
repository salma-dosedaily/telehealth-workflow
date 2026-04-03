# Project Context & Changelog: Lean Telehealth Automation

## 📖 Project Overview
We are building a fully automated, "Lean" Telehealth data pipeline. This system captures patient bookings, processes post-consultation notes using AI, and routes data to our Data Warehouse (BigQuery) and Marketing Platform (Klaviyo) via our CDP (RudderStack). 

**Primary Goal:** To completely bypass expensive CRM routing (e.g., HubSpot Professional / Salesforce) by utilizing a "Warehouse-First" architecture and custom Google Cloud Functions.

---

## 🏗️ Architecture & Tech Stack
* **Intake:** Calendly (Teams Tier - API Enabled)
* **Consultation:** Zoom (Pro/Business Tier - Cloud Recording & Transcripts Enabled)
* **Logic Engine:** Google Cloud Function (Python 3.10+) + Gemini 2.5 API
* **CDP / Router:** RudderStack
* **Data Warehouse:** Google BigQuery
* **Marketing Automation:** Klaviyo

---

## 🔄 Core Data Flows

### Flow 1: Active Patient Post-Call Lifecycle
1. Patient books via Calendly -> Syncs to BigQuery/RudderStack.
2. Patient and Nutritionist (Kim) meet on Zoom.
3. Call ends -> **Fast path (optional):** Zoom sends `meeting.ended` ~1 min after call end; GCF enqueues a Cloud Task that **polls** Zoom’s API for the transcript every 2 min. As soon as the transcript is ready (~5–15 min), GCF runs the pipeline so Klaviyo can send the follow-up email. See [ZOOM_FAST_PATH_SETUP](docs/ZOOM_FAST_PATH_SETUP.md). **Fallback:** Zoom later sends `recording.transcript_completed` (often 15–45+ min; see [TROUBLESHOOTING](docs/TROUBLESHOOTING.md)).
4. GCF executes logic:
    * Downloads `.vtt` transcript.
    * Runs **No-Show Safety Check** (halts if transcript is < 50 words).
    * Passes transcript to Gemini API to extract sentiment, internal summary, and voice-dictated notes (`kims_custom_note`).
5. GCF constructs a JSON payload and sends it to RudderStack.
6. RudderStack routes:
    * Raw data to BigQuery (for historical LTV/record keeping).
    * `Telehealth_Call_Finished` Event to Klaviyo (triggers the post-call email flow populated with AI notes).

### Flow 2: Bulk Acquisition / Lead Invites (Reverse ETL)
1. BigQuery acts as the Single Source of Truth for all historical data.
2. RudderStack runs SQL queries against BigQuery to identify contacts where `is_active_patient = FALSE`.
3. RudderStack automatically syncs these contacts into a specific Klaviyo Segment.
4. Klaviyo triggers a "Nutrition Program Invite" campaign based on segment membership.

---

## 📝 Changelog / Decision History

### [2026-04-03] - Feature: Manual "No Show" via Google Form product dropdown
* **Why:** Kim needs a way to log no-shows when Zoom duration data isn't available or she submits the form manually without a recording.
* **Google Form:** Add "No Show" as a selectable option in the existing "Product/Program" dropdown — no new form fields required.
* **`_canonical_product_name_for_klaviyo()`:** Now maps any variant of "No Show" / "noshow" / "no-show" → stable `"No Show"` string.
* **`process_form_submission()`:** When `canon_product == "No Show"`, bypasses the `kims_note` requirement and duration check, then sends `Telehealth_Call_Finished` with `userId = patient_email`, `productName = "No Show"`, and `attended = False`. A RudderStack identify is sent first (`completed_call=False`) so Klaviyo profile gets `telehealth_last_product = "No Show"`.
* **Event routing decision:** Sends `Telehealth_Call_Finished` (not a separate `Telehealth_Call_No_Show` event) so that one Klaviyo flow handles all form submissions. A Conditional Split on `productName == "No Show"` immediately after the trigger routes no-shows to the "We Missed You" email and everyone else to the AI notes follow-up.
* **App Script (`scripts/google_form_to_rudderstack.js`):** Detects `isNoShow` from the product field. When true, only email is required (note and duration checks are skipped). Payload is sent as-is; the backend handles the routing.
* **Klaviyo setup:** In the existing `Telehealth_Call_Finished` flow, add a Conditional Split immediately after the trigger: `productName equals "No Show"` → YES branch → "We Missed You" email; NO branch → existing AI notes email.

### [2026-03-27] - Fix: Separate Telehealth Slack webhook from shared SLACK_WEBHOOK_URL (ETL clash)
* **Root cause:** Telehealth and ETL both used GSM secret `SLACK_WEBHOOK_URL`; updating it for telehealth pointed ETL jobs at the telehealth Incoming Webhook, so ETL alerts appeared in `#telehealth-calls`.
* **New secret:** `SLACK_WEBHOOK_URL_TELEHEALTH` — Incoming Webhook URL for telehealth-only (Calendly 15-min reminder, Klaviyo email-sent callback).
* **scripts/setup_slack_webhook_telehealth_secret.sh:** Creates secret, adds version from `TELEHEALTH_SLACK_WEBHOOK_URL`, grants default compute SA `secretAccessor`.
* **scripts/restore_etl_slack_webhook.sh:** Adds a new version to `SLACK_WEBHOOK_URL` from `ETL_SLACK_WEBHOOK_URL` so ETL returns to its channel.
* **scripts/deploy_calendly_reminder.sh / deploy_klaviyo_email_sent.sh:** Prefer `--set-secrets=SLACK_WEBHOOK_URL=SLACK_WEBHOOK_URL_TELEHEALTH:latest` when that secret exists; else env `SLACK_WEBHOOK_URL`.
* **Ops:** Restore `SLACK_WEBHOOK_URL` to the ETL webhook after creating `SLACK_WEBHOOK_URL_TELEHEALTH`; redeploy telehealth functions.
* **scripts/apply_slack_webhook_separation_fix.sh:** One-shot runner: telehealth secret + optional ETL restore + redeploy Calendly reminder and Klaviyo email-sent functions.
* **docs/SLACK_WEBHOOK_SEPARATION.md:** Why two webhooks, table of secrets, usage.
* **.env.example:** Slack separation pointers and script reference.

### [2026-03-27] - Fix: Klaviyo splits (Liver), attended visibility, summary notes; form email/name keys
* **main.py:** Google Form path accepts JSON keys `email` / `name` in addition to `patient_email` / `patient_name`; webhook routes form when `email` + note present.
* **main.py:** `_canonical_product_name_for_klaviyo()` maps dropdown text (e.g. "Liver", "liver program") to stable `productName` values `Liver` / `Cholesterol` / `Bundle` so flow conditional splits match. Also sends duplicate `Product` property for templates that use that name.
* **main.py:** `_normalize_kims_note_to_summary()` collapses newlines to a single paragraph so `{{ event.kims_custom_note }}` reads as a summary in email (not numbered/bullet layout).
* **main.py:** `Telehealth_Call_Finished` (form) now includes `attended`, `call_attended` (bool), `attended_str` (`"true"`), `telehealth_attended` (`"yes"`) for Klaviyo filters; identify traits add `telehealth_call_attended` and `telehealth_attended` for retention segments.
* **scripts/google_form_to_rudderstack.js:** Payload includes `email` and `name` aliases alongside patient fields.
* **Klaviyo UI:** Conditional splits on product must use **properties from the trigger event** (e.g. `productName` on `Telehealth_Call_Finished`), not "Properties about someone" — the latter is profile data and explains "All Else" / wrong branch when the event had Liver selected.

### [2026-03-27] - Fix: Sync productName to Klaviyo profile for "Properties about someone" splits
* **main.py:** `_rudderstack_identify()` accepts `telehealth_product` and sets profile traits `productName` and `telehealth_last_product` to the canonical value (Liver / Cholesterol / Bundle) on each form completion. Klaviyo conditional splits that only offer **Properties about someone** (no trigger-event option) can keep using `productName` on the profile; identify runs after merging Firestore product so Zoom-sourced product is included.

### [2026-03-27] - Feat: Four major enhancements to telehealth automation
* **main.py:** Added four critical features for better patient tracking and Klaviyo flow management:
  1. **Product information in Zoom flow**: `meeting.ended` events now extract product type (Liver/Cholesterol/Bundle) from Zoom meeting topic and pass as `productName` to RudderStack/Klaviyo. Also stored in Firestore so form submissions can retrieve it. Enables product-specific follow-up flows even when form doesn't include product field.
  2. **No-show event**: New `Telehealth_Call_No_Show` event sent to RudderStack/Klaviyo when call duration < 10 min (changed from 5 min threshold). Enables separate Klaviyo flow for no-shows (e.g., reschedule reminder). Meeting.ended now checks: < 10 min = no-show event, >= 10 min = completed call event.
  3. **Profile property for completed calls**: `_rudderstack_identify()` now sets `completed_telehealth_call: true` trait when form is submitted. Klaviyo profiles can be segmented by patients who completed at least one call vs. those who haven't (for targeted campaigns).
  4. **Bullet point support in Kim's notes**: Form submission preserves line breaks and formatting in `kims_custom_note` (previously stripped). Normalizes line endings to `\n` for consistency. Klaviyo emails can now display bullet points and multi-line notes correctly.
* **main.py:** `send_no_show_to_rudderstack()` function sends `Telehealth_Call_No_Show` event with `attended: false` property. `send_meeting_ended_to_rudderstack()` and `send_form_submission_to_rudderstack()` now accept optional `product_name` parameter.
* **main.py:** `store_meeting_ended()` now stores `product_name` in Firestore so form submission can retrieve it when matching meeting_uuid.
* **scripts/google_form_to_rudderstack.js:** Already supports product field (no changes needed); form script preserves formatting in paragraph fields.
* **Deployment:** Redeploy `telehealth_webhook_handler` to enable all four features: `bash scripts/deploy_zoom_webhook.sh`

### [2026-03-27] - Fix: Calendly webhook and reminder missing Firestore DB and Slack config
* **Deployed:** Redeployed `calendly_webhook_handler` with `FIRESTORE_DATABASE_ID=telemeetinglog` so Zoom links and prefilled form URLs are stored in correct Firestore database.
* **Deployed:** Redeployed `calendly_reminder_handler` with `FIRESTORE_DATABASE_ID=telemeetinglog` and `SLACK_WEBHOOK_URL` so 15-minute reminders are sent to Slack with Zoom links.
* **Root cause:** Both functions were deployed without critical environment variables, causing Zoom links to not be stored and Slack reminders to not be sent.
* **Verification:** Checked Firestore `calendly_prefilled_forms` collection; some bookings have Zoom links, others missing (created before 2026-03-16 fix). New bookings will store Zoom links correctly.

### [2026-03-17] - Feat: MCP service account script (cross-project dosedaily-raw + dosedaily-prod)
* **scripts/create_mcp_service_account_cross_project.sh:** Creates SA `mcp-bigquery-cross@dosedaily-raw.iam.gserviceaccount.com` with same IAM roles as salma.elmasry@dosedaily.co on both dosedaily-raw and dosedaily-prod. Script lists reference user roles, then creates SA and grants union of roles in both projects. Use for BigQuery MCP so Cursor can query both projects without user re-auth.
* **docs/MCP_SERVICE_ACCOUNT_SETUP.md:** Prerequisites (gcloud auth), usage (run script, optional --dry-run), and how to use the SA with MCP (ADC or key file, GOOGLE_APPLICATION_CREDENTIALS). Security note: do not commit key file.

### [2026-03-17] - Feat: productName from form for Klaviyo flow splits (Liver / Cholesterol / Bundle)
* **main.py:** Form submission now accepts optional `product_name` or `productName` and sends it as event property `productName` to RudderStack/Klaviyo. Enables flow conditional splits (e.g. productName contains Liver / Cholesterol / Bundle) when the Google Form includes a product field. Existing forms without the field unchanged.
* **scripts/google_form_to_rudderstack.js:** Map form question "Product" or "Program" to payload `product_name` so the Cloud Function forwards it as `productName`. Setup comment lists optional form field. Name check excludes "product" so "Product" does not overwrite patient name.
* **docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md:** Document event property `productName`, merge variable `{{ event.productName }}`, and "Flow splits" section explaining that splits are event-based and require the form to send product for routing.

### [2026-03-16] - Fix: Slack reminder missing Zoom link for some users
* **functions/calendly/main.py:** `_extract_zoom_join_url` made robust: (1) check `location.data.join_url` when location is a dict; (2) when `location` or `locations[]` item is a string (custom location), extract Zoom URL via regex; (3) fallback recursive scan of event resource for any `zoom.us/j/` URL so odd Calendly payload shapes still yield a link. Ensures new bookings get `zoom_join_url` stored in Firestore when Calendly returns Zoom in non-standard structure.
* **functions/calendly_reminder/main.py:** Log a warning when sending a Slack reminder for a document that has no `zoom_join_url` (reminder still sent; Zoom link block omitted). Helps identify which bookings lack Zoom in Firestore (e.g. created before this fix or event type without Zoom).

### [2026-03-11] - Feat: Sync project docs to Notion
* **scripts/sync_docs_to_notion.py:** Script to create Notion pages from docs/*.md and CHANGELOG.md. Reads NOTION_API_KEY and NOTION_PARENT_PAGE_ID from env; sends markdown via Notion API `markdown` parameter. No API key stored in repo.
* **docs/NOTION_SYNC.md:** How to get a Notion API key, create a parent page, share it with the integration, and run the sync.
* **.env.example:** NOTION_API_KEY and NOTION_PARENT_PAGE_ID (optional) for Notion sync.

### [2026-03-11] - Feat: Klaviyo flow webhook → Slack when follow-up email is sent
* **functions/klaviyo_email_sent:** New Cloud Function. Receives POST from Klaviyo flow Webhook action (placed after "Send Email"); body: `email`, optional `patient_name`. Optional auth: header `X-Klaviyo-Callback-Secret`. Posts to Slack: "Follow-up email sent to {name} ({email})".
* **scripts/deploy_klaviyo_email_sent.sh:** Deploy with SLACK_WEBHOOK_URL, optional KLAVIYO_CALLBACK_SECRET; allow-unauthenticated so Klaviyo can POST.
* **docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md:** Part 7 rewritten with step-by-step: 7.1 Deploy callback function, 7.2 Add Webhook action in Klaviyo (URL, optional header, body with `{{ person.email }}`, `{{ event.patient_name }}`). Quick Checklist item 8 for optional Slack notification.

### [2026-03-11] - Slack reminder clean message; doc Klaviyo email-sent notification
* **functions/calendly_reminder/main.py:** Removed raw Zoom and Form URLs from the Slack message. Message is now only the attachment block (Patient, Scheduled, Zoom Link, Form Link) with link text "Join Zoom meeting" and "Open prefilled Telehealth Note form". No long URL text in the body.
* **docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md:** Part 7 — options to get notified when the follow-up email is sent (Klaviyo webhooks with Advanced KDP, flow action, or Metrics API polling → e.g. Slack).

### [2026-03-11] - Fix: Duplicate "Anonymous" Telehealth_Call_Finished from Zoom meeting.ended
* **main.py:** Idempotency for meeting.ended: before sending to RudderStack, check if we already have this meeting_uuid in Firestore (`get_meeting_ended`). If yes, return "Already processed" and skip sending again. Zoom often delivers the webhook twice (retries), which caused two identical Anonymous activities in Klaviyo for the same meeting.

### [2026-03-10] - Fix: Klaviyo "Skipped: Missing Email" — identify before track
* **main.py:** Send RudderStack `identify` call (userId + traits.email, firstName, lastName) before `track` in the form submission path. Ensures Klaviyo profile has `email` so follow-up flows stop skipping with "Skipped: Missing Email". `_rudderstack_identify()` derives `/v1/identify` URL from `RUDDERSTACK_URL` and posts Basic-auth payload; logs success/failure without failing the form submission.

### [2026-03-10] - Feat: Nutritionist instruction manual (non-technical)
* **docs/NUTRITIONIST_INSTRUCTION_MANUAL.md:** Step-by-step guide for the nutritionist (Kim): booking → Slack reminder → call → form → follow-up email. Simple language (6th grader level), Mermaid diagrams for flow, quick tips, and troubleshooting.

### [2026-03-10] - Fix: event_start_utc null in calendly_prefilled_forms (Slack reminder needs it)
* **functions/calendly/main.py:** When the invitee resource doesn't have start_time/end_time, fall back to the fetched event resource (ev_resource), which includes start_time and end_time. Fixes event_start_utc being null in Firestore so the Slack 15-min reminder can match bookings.

### [2026-03-10] - Fix: Kim's note prefilled with patient name (wrong entry ID)
* **docs/CALENDLY_PREFILL_FORM.md:** Section 1: clearer "get entry IDs" steps—fill ONE field at a time in Get pre-filled link to identify email vs name. Do not fill Kim's Note. Troubleshooting #7: when Kim's note shows patient name, PREFILL_FORM_ENTRY_NAME is set to Kim's Note's ID; re-get name-only entry ID and redeploy.

### [2026-03-10] - Feat: Slack 15-min reminder, Google Sheet doc, fix host_email null
* **functions/calendly_reminder:** New Cloud Function for Slack 15-min-before-call reminder. Cloud Scheduler triggers every 5 min; finds Firestore `calendly_prefilled_forms` with event_start in next 15 min, sends Slack with prefilled link, sets `reminder_sent_at`. Free (Slack Incoming Webhook).
* **scripts/deploy_calendly_reminder.sh, setup_calendly_reminder_scheduler.sh:** Deploy and schedule the reminder.
* **main.py:** Fix host_email null: add fallback `get_zoom_host_email_from_past_meeting(meeting_uuid)` via Zoom GET /past_meetings/{uuid} to get user_email when meeting.ended omits host_email and host_id resolution fails.
* **docs/CALENDLY_PREFILL_FORM.md:** Section 6: Slack 15-min reminder setup. Section 7: Google Sheet feed from BigQuery (Looker Studio, Connected Sheets, scheduled query). Updated "Getting the link" to recommend Slack and Sheet as free options.

### [2026-03-10] - Feat: Email prefilled form link to Kim when someone books (SendGrid)
* **functions/calendly/main.py:** When a prefilled URL is built and the booking is not canceled, send an email to the host (Calendly host_email or HOST_EMAIL) with the prefilled form link. Uses SendGrid API; SENDGRID_API_KEY from GSM, SENDGRID_FROM_EMAIL (verified sender), HOST_EMAIL (fallback recipient). Logs success/failure; does not fail webhook on email errors.
* **scripts/deploy_calendly_webhook.sh:** Wire SENDGRID_API_KEY (secret), SENDGRID_FROM_EMAIL, HOST_EMAIL when set.
* **docs/CALENDLY_PREFILL_FORM.md:** New section 5: SendGrid setup (API key, GSM secret, sender verification, deploy), plus troubleshooting for email not received.
* **.env.example:** Document Calendly email env vars.

### [2026-03-10] - Fix: Calendly prefill use name/email from booking page; payload fallback and logging
* **functions/calendly/main.py:** Prefilled URL now always uses the invitee name and email from the Calendly booking (API response). Added fallback to webhook payload `email`/`name` and `payload.invitee` when API omits them. Log message now includes exact email and name used for prefill so you can verify in Cloud Logging.
* **docs/CALENDLY_PREFILL_FORM.md:** Clarified that name/email come from the booking page when they click "Book meeting"; use the link for that booking (match invitee_email/invitee_name), not an old/test row.

### [2026-03-10] - Feat: Store Calendly prefilled form URL in Firestore (same as Zoom DB)
* **functions/calendly/main.py:** When a prefilled form URL is built, also write it to Firestore collection `calendly_prefilled_forms` (doc id = event_uuid_invitee_uuid; fields: invitee_email, invitee_name, prefilled_form_url, event_start_utc, created_at). Enables lookup by patient email without querying BigQuery. Uses same FIRESTORE_DATABASE_ID as Zoom (e.g. telemeetinglog) when set.
* **functions/calendly/requirements.txt:** Added google-cloud-firestore.
* **scripts/deploy_calendly_webhook.sh:** Pass FIRESTORE_DATABASE_ID into function env when set.
* **docs/CALENDLY_PREFILL_FORM.md:** Document that form does not auto-open; link is in BQ and Firestore. Added FIRESTORE_DATABASE_ID to env table and deploy example. Troubleshooting: "POST 200 but no prefilled link in BQ" — ensure table has column, check logs, get link from Firestore by invitee_email.

### [2026-03-10] - Fix: Resolve host_email from Zoom host_id when meeting.ended omits it
* **main.py:** Zoom meeting.ended often sends `host_id` but not `host_email`. We now call Zoom API GET /users/{host_id} to resolve email when host_email is missing, then store and send it to RudderStack. Requires Zoom OAuth with scope that allows user read (e.g. user:read or user:read:admin) for the token used by the webhook.

### [2026-03-10] - Feat: Form without duration field — Kim does not enter meeting duration
* **scripts/google_form_to_rudderstack.js:** Duration is optional. If the form has no "Call duration (minutes)" field, use DEFAULT_DURATION_MINUTES (10) so Kim only fills email, name, note, and Meeting UUID.
* **main.py:** Form submission accepts missing duration; use DEFAULT_FORM_DURATION_MINUTES (10) so backend and Klaviyo flow (duration >= 5) still work.

### [2026-03-10] - Fix: Use start_time when Zoom sends wrong meeting.ended duration
* **main.py:** When Zoom reports duration &lt; 5 min but we have start_time, compute duration from start_time to now and use the larger value. Fixes meetings that were open a long time (e.g. started before deploy) but Zoom sends 0 or 30 seconds.

### [2026-03-10] - Feat: Prefill Google Form (patient email, name) from Calendly webhook
* **functions/calendly/main.py:** Optional prefilled form URL: when PREFILL_FORM_BASE_URL and PREFILL_FORM_ENTRY_EMAIL (and optionally PREFILL_FORM_ENTRY_NAME) are set, build a Google Form URL with invitee email and name and store it in row field `prefilled_form_url`. Meeting UUID is not available at booking time; Kim pastes it after the Zoom call.
* **scripts/deploy_calendly_webhook.sh:** Pass PREFILL_FORM_* env vars when set; point to docs/CALENDLY_PREFILL_FORM.md.
* **docs/CALENDLY_PREFILL_FORM.md:** How to get form entry IDs, add BigQuery column `prefilled_form_url`, set env vars, and use the link so Kim only fills notes + duration + Meeting UUID.
* **docs/FORM_MEETING_UUID_SETUP.md:** Section 2 updated to point to Calendly prefill doc.

### [2026-03-10] - Fix: Zoom meeting.ended duration is seconds; convert to minutes for check and storage
* **main.py:** Zoom meeting.ended webhook sends `duration` in **seconds**. We now convert to minutes (`duration_seconds // 60`) for the no-show check (≥ 5 min) and for Firestore/RudderStack so stored and downstream values are in minutes. Previously 30 in Firestore meant Zoom sent 30 (seconds) and we treated it as 30 min.

### [2026-03-10] - Fix: Use named Firestore DB (e.g. telemeetinglog) and Klaviyo flow skips
* **main.py:** Added FIRESTORE_DATABASE_ID env; when set (e.g. telemeetinglog), Firestore client uses that database instead of (default). Fixes 404 when the project has a named DB but no (default).
* **scripts/deploy_zoom_webhook.sh:** Pass FIRESTORE_DATABASE_ID into function env when set; document FIRESTORE_DATABASE_ID=telemeetinglog for named DB.
* **docs/TROUBLESHOOTING.md:** Firestore section: if you created a named DB (telemeetinglog), set FIRESTORE_DATABASE_ID and redeploy. Klaviyo section: concrete steps when flow shows "Skipped: 7" and Delivered 0 (trigger filter on source, email step filters, profile must exist).
* **.env.example:** FIRESTORE_DATABASE_ID optional.

### [2026-03-10] - Fix: Firestore "database (default) does not exist" — create database in setup
* **scripts/setup_firestore_form_secret.sh:** After enabling Firestore API, create the (default) Firestore database with `gcloud firestore databases create --location=REGION` if missing. Enabling the API alone is not enough; the database must be created once per project.
* **docs/TROUBLESHOOTING.md:** New section "Firestore: The database (default) does not exist" with Console and gcloud fix.
* **docs/FORM_MEETING_UUID_SETUP.md:** Document that the setup script now creates the Firestore database.

### [2026-03-10] - Investigate: Form prefill, meeting after deploy, Klaviyo 7 skips
* **docs/TROUBLESHOOTING.md:** Added "Google Form: Patient email not prefilling when pasting meeting link" — use prefilled form link (Get pre-filled link) to open form with email filled; Zoom URL does not contain email. Added "Klaviyo: RudderStack events succeed but flow shows X skips" — trigger filter on `source` (must include `google_form`), userId = patient email must have Klaviyo profile, checklist.
* **docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md:** Part 3: do not filter trigger by source=zoom only (form sends source=google_form). Part 5: form path userId=patient_email must exist as profile or skips occur.
* **docs/FORM_MEETING_UUID_SETUP.md:** Optional step 2: prefill Patient Email via Get pre-filled link; renumbered steps.

### [2026-03-10] - Form: accept Zoom join URL in Meeting UUID field; backend lookup by meeting ID
* **scripts/google_form_to_rudderstack.js:** Added `normalizeMeetingIdentifier()`: if Kim pastes a Zoom join URL (e.g. https://us06web.zoom.us/j/89166792057?pwd=...), extract the numeric meeting ID and send that so the backend can resolve it.
* **main.py:** Firestore now stores Zoom’s numeric `id` (meeting ID) when present in meeting.ended. `get_meeting_ended()` accepts a Zoom UUID, a numeric meeting ID, or a full Zoom join URL and looks up by UUID first, then by meeting_id.
* **docs/FORM_MEETING_UUID_SETUP.md:** Documented that Kim can paste either UUID or join link in the Meeting UUID field.

### [2026-03-10] - Firestore + FORM_SUBMIT_SECRET setup for Meeting UUID and form-only auth
* **scripts/setup_firestore_form_secret.sh:** One-shot script: enables Firestore API, grants default compute SA `roles/datastore.user`, creates FORM_SUBMIT_SECRET in GSM (tagged, SA granted secretAccessor). Ensures Firestore is enabled when using meeting_uuid so form submissions get host_email/meeting_date.
* **scripts/deploy_zoom_webhook.sh:** Wires FORM_SUBMIT_SECRET from GSM when the secret exists (same pattern as POLL_SECRET).
* **scripts/google_form_to_rudderstack.js:** SETUP comments clarified: Meeting UUID field (optional) ties form to Zoom meeting for host_email/meeting_date; FORM_SUBMIT_SECRET must match value in GCP; Firestore required when using Meeting UUID.
* **docs/FORM_MEETING_UUID_SETUP.md:** Setup guide: enable Firestore, add Meeting UUID field, create and set FORM_SUBMIT_SECRET in GSM and form script.
* **.env.example:** Documented FORM_SUBMIT_SECRET and Firestore requirement for Meeting UUID.

### [2026-03-09] - Form submission → Cloud Function → RudderStack/Klaviyo (verify patient email)
* **main.py:** Form submission path: POST with `patient_email`, `kims_custom_note`, `duration` (and optional `meeting_uuid`, `patient_name`) is routed to `process_form_submission`. Validates email format and duration >= 5 min; sends to RudderStack with **userId=patient_email** so Klaviyo can send follow-up emails. Optional `FORM_SUBMIT_SECRET` (header `X-Form-Secret`) for auth. Optional Firestore store of `meeting.ended` for form verification and merging Zoom context (host_email, meeting_date) when form includes `meeting_uuid`.
* **scripts/google_form_to_rudderstack.js:** Form now POSTs to the **Telehealth Cloud Function URL** (same as Zoom webhook) instead of RudderStack directly. Payload: patient_email, patient_name, kims_custom_note, duration, optional meeting_uuid. Optional X-Form-Secret header.
* **requirements.txt:** Added google-cloud-firestore for meeting.ended store/lookup.

### [2026-03-09] - Meeting.ended → RudderStack immediately (no poll)
* **main.py:** `meeting.ended` now sends `Telehealth_Call_Finished` to RudderStack immediately—no poll task, no transcript wait. Removed `create_poll_task`, `_handle_poll_transcript`, and Cloud Tasks poll path. `kims_custom_note` is set to "No custom notes provided." (use Google Form for notes if needed).

### [2026-03-09] - Remove recording.transcript_completed; poll-only path
* **main.py:** Removed `recording.transcript_completed` handler; transcript is obtained only via `meeting.ended` + poll. When Zoom API auth is missing, logs suggest Google Form fallback.
* **Docs:** Updated SETUP_STEP_BY_STEP, TROUBLESHOOTING, ZOOM_FAST_PATH_SETUP, KLAVIYO_POST_CALL_EMAIL_SETUP to reflect poll-only flow.

### [2026-03-09] - Google Form no-show check + Klaviyo duration filter
* **scripts/google_form_to_rudderstack.js:** Added required "Call duration (minutes)" field; only sends to RudderStack when duration >= 5 min (matches Zoom pipeline, avoids no-show triggers).
* **docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md:** Added trigger filter for flow: Event property `duration` >= 5 so emails send only when call happened and lasted 5+ min.

### [v1.0.0] - Architecture Finalized
* **Removed:** HubSpot CRM from the critical path to avoid 2,000 "Marketing Contact" limits and $1,200/mo tier upgrades.
* **Removed:** Make.com/Integromat as the middleman, opting for a custom Google Cloud Function (Python) to achieve $0 operating costs and tighter control over transcript data.
* **Added:** "Voice Dictation" feature. The nutritionist no longer types notes into a CRM. Instead, they say, "Summary for the email: [Note]" before ending the Zoom call. Gemini AI extracts this and passes it to Klaviyo via the `kims_custom_note` variable.
* **Added:** Klaviyo Data Strategy. Post-call emails will be triggered by **Metrics/Events** (`Telehealth_Call_Finished`), while Bulk Invites will be triggered by **List/Segment** additions.

---

## 💻 Current Codebase State
* `main.py` (Drafted): Python script for Google Cloud Function. 
    * *Features built:* Zoom webhook endpoint validation, Transcript download, No-Show safety check (word count), Gemini API integration for sentiment/note extraction, HTTP POST to RudderStack.
* `requirements.txt` (Drafted): Contains `functions-framework`, `requests`, `google-generativeai`.

---

---

### [2026-03-02] - Feat - Calendly webhook Cloud Function
* **Added:** `functions/calendly/` — Cloud Function that receives Calendly webhooks (invitee.created, invitee.canceled), fetches invitee details via Calendly API, writes to BigQuery `telehealth.calendly_bookings`.
* **Added:** BigQuery table `dosedaily-raw.telehealth.calendly_bookings` (event_type, invitee_email, event_start, host_email, etc.).
* **Added:** `scripts/register_calendly_webhook.py` — Registers Calendly webhook subscription via API (Calendly has no UI to connect Cloud Functions).
* **Docs:** Updated SETUP_STEP_BY_STEP.md Step 4.2 with Calendly webhook deploy and registration.

### [2026-03-02] - Feat - RudderStack data plane secrets and HTTP API auth
* **GCP:** Created `RUDDERSTACK_URL` (https://dosedaily.dataplane.rudderstack.com/v1/track) and `RUDDERSTACK_WRITE_KEY` in Secret Manager; granted compute SA access.
* **main.py:** Switched to `RUDDERSTACK_URL` + `RUDDERSTACK_WRITE_KEY`; added Basic auth for RudderStack HTTP API (per docs).
* **Docs:** Updated SETUP_STEP_BY_STEP.md with data plane URL and write key usage.

### [2026-03-02] - Feat - Service account and telehealth dataset in dosedaily-raw
* **GCP:** Created service account `data-dosedaily@dosedaily-raw.iam.gserviceaccount.com` (display name "Data (data@dosedaily.co)") in project **dosedaily-raw**. Granted `roles/bigquery.admin` and `roles/secretmanager.secretAccessor`.
* **BigQuery:** Created dataset `telehealth` in **dosedaily-raw** (location US) for telehealth event and booking data.
* **Docs:** Updated `docs/SETUP_STEP_BY_STEP.md` with project/dataset/SA reference.

### [2026-03-02] - Feat - Step-by-step setup guide (Zoom, Calendly, RudderStack, GCP)
* **Added:** `docs/SETUP_STEP_BY_STEP.md` — End-to-end checklist: GCP (project, APIs, Secret Manager, deploy Cloud Function), Zoom (Cloud Recording + Audio Transcript, app, webhook URL, subscribe to Transcript completed, secret token), RudderStack (HTTP source, BigQuery warehouse, Klaviyo destination), Calendly (API token, sync to BQ/RS), identity resolution, Klaviyo flow, and test steps.

### [2026-03-02] - Feat - Technical plan, regex extraction, duration check, permission email
* **Added:** `docs/TELEHEALTH_WORKFLOW_PLAN.md` — Technical Plan of Attack: trigger strategy (`recording.transcript_completed`), connection logic, safety checks (duration > 5 min, transcript exists, no-show), identity resolution (meeting_uuid → Calendly), HIPAA-lean (GSM, minimal PHI, BAA), Mermaid data flow.
* **Added:** Regex-first extraction for `kims_custom_note`: pattern `(?:summary|notes)\s+for\s+the\s+email\s*:\s*(.+?)` with `extract_kims_custom_note_regex()` in `main.py`; Gemini used only for sentiment/summary and as fallback when regex finds no note.
* **Added:** Safety check: meeting duration ≥ 5 minutes (`MIN_DURATION_SECONDS = 300`) before processing; Zoom `object.duration` (seconds) validated.
* **Added:** `meeting_date` in RudderStack payload (from `start_time` / `start_time_iso`).
* **Added:** `docs/PERMISSION_REQUEST_EMAIL.md` — Concise stakeholder email draft for Zoom (Cloud Recording + Audio Transcripts, webhook secret), Calendly (API token for data@dosedaily.co), and service account confirmation.
* **Doc:** Fallback path: Google Form → Klaviyo bridge described in plan when transcript extraction fails.

---

### [2026-03-09] - Feat - Zoom OAuth flow complete; fast path fully enabled
* **OAuth Success:** Completed Zoom OAuth authorization via `zoom_oauth_callback` function. Refresh token stored in GSM (`ZOOM_REFRESH_TOKEN`).
* **telehealth_webhook_handler:** Redeployed with `ZOOM_REFRESH_TOKEN` wired from GSM. Fast path is now fully operational.
* **Flow:** When `meeting.ended` webhook fires, function uses refresh token to get access token, polls Zoom API for transcript, and sends to RudderStack/Klaviyo within ~5-15 min (vs 25-60+ min with transcript webhook alone).

### [2026-03-07] - Feat - Zoom OAuth credentials and callback function aligned
* **GSM:** Added `ZOOM_CLIENT_ID` (pEBl08rgSy_gBf3cb_HJA), `ZOOM_CLIENT_SECRET`, updated `ZOOM_SECRET_TOKEN` (v2) for new Zoom app.
* **zoom_oauth_callback:** Updated to handle OAuth callback at root path (no `/callback` suffix) to match Zoom's generated OAuth URL; `_redirect_uri` returns `https://zoom-oauth-callback-pshv76iija-uc.a.run.app`. Added `GCP_PROJECT` env var so refresh token is stored in GSM on success.
* **telehealth_webhook_handler:** Redeployed with new `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`, `ZOOM_SECRET_TOKEN` from GSM.
* **Zoom app:** Development mode; OAuth URL `https://zoom.us/oauth/authorize?...&redirect_uri=https://zoom-oauth-callback-pshv76iija-uc.a.run.app` works for internal use (only account owner can authorize).

### [2026-03-05] - Feat - Zoom fast path without S2S: General App (OAuth 2.0) + refresh token
* **main.py:** Support **ZOOM_REFRESH_TOKEN** (General App user OAuth). When S2S is not available, use a General App; meeting host authorizes once; we store refresh token and use it server-side to poll the recordings API. `get_zoom_oauth_token()` tries S2S first, then refresh token; when refreshing, Zoom returns a new refresh token and we persist it to Secret Manager so the next run has a valid token.
* **main.py:** `meeting.ended` enqueues poll task when **either** S2S (ZOOM_ACCOUNT_ID) **or** refresh token (ZOOM_REFRESH_TOKEN) is configured.
* **scripts/zoom_oauth_authorize.py:** One-time local OAuth flow: opens browser for Zoom authorize, captures callback, exchanges code for tokens, prints and optionally stores refresh token in GSM. Requires General App with redirect `http://127.0.0.1:8765/callback` and scope `recording:read`.
* **requirements.txt:** Added `google-cloud-secret-manager` (for persisting new refresh token after Zoom refresh).
* **docs/ZOOM_FAST_PATH_SETUP.md:** New section **2b. Alternative: General App (OAuth 2.0)** when S2S is not available: create General App, add redirect and scope, run `zoom_oauth_authorize.py`, grant function SA secretAccessor + secretVersionAdder on ZOOM_REFRESH_TOKEN.
* **.env.example, deploy script:** ZOOM_REFRESH_TOKEN; deploy wires it from GSM when present.

### [2026-03-05] - Feat - GCP setup script for Zoom fast path; queue and POLL_SECRET created
* **scripts/setup_gcp_fast_path.sh:** One-shot GCP setup for fast path: enable Cloud Tasks API, create queue `telehealth-poll`, create POLL_SECRET in GSM (random), tag with project_name, grant compute SA secretAccessor. Run once per project.
* **Executed:** Cloud Tasks API enabled; queue `telehealth-poll` created in dosedaily-raw/us-central1; POLL_SECRET created in GSM and IAM bound to default compute SA.

### [2026-03-05] - Feat - Zoom fast path (meeting.ended + poll) and summary-only for Klaviyo
* **main.py:** Accept **meeting.ended** webhook; enqueue **Cloud Task** to poll Zoom’s recordings API every 2 min until transcript is ready, then download and run the same pipeline. Enables follow-up email in **~5–15 min** instead of 25–60 min. **recording.transcript_completed** kept as fallback.
* **main.py:** **Summary-only mode** (`SUMMARY_ONLY=True`): only nutritionist summary (`kims_custom_note`) is extracted (regex + optional Gemini if regex misses); sentiment and internal summary skipped for faster handler and quicker Klaviyo email.
* **main.py:** Zoom **Server-to-Server OAuth** for polling GET `/meetings/{uuid}/recordings`; double-encode UUID for API; download transcript with Bearer token.
* **requirements.txt:** Added `google-cloud-tasks`.
* **docs/ZOOM_FAST_PATH_SETUP.md:** Setup: Cloud Tasks queue, Zoom S2S OAuth app, env (TELEHEALTH_WEBHOOK_URL, POLL_SECRET, ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET), subscribe Zoom to meeting.ended.
* **.env.example:** TELEHEALTH_WEBHOOK_URL, POLL_SECRET, GCP_PROJECT, GCP_REGION, TASKS_QUEUE, ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET, SUMMARY_ONLY.
* **scripts/deploy_zoom_webhook.sh:** Set GCP_PROJECT, GCP_REGION, TASKS_QUEUE; wire POLL_SECRET and Zoom OAuth from GSM when present.
* **main.py:** When Zoom Server-to-Server OAuth is not configured, `meeting.ended` returns 200 and does not enqueue poll tasks (avoids wasted tasks; transcript_completed webhook still delivers).
* **docs/ZOOM_FAST_PATH_SETUP.md:** Documented that the fast path requires a Zoom S2S OAuth app; if only Webhook-only or General app is available, use Recording → Transcript completed only (15–60 min delay).
* **scripts/setup_gcp_fast_path.sh:** One-shot GCP setup: enable Cloud Tasks API, create queue `telehealth-poll`, create POLL_SECRET in GSM (random value), tag with project_name, grant compute SA secretAccessor. Echo next steps for Zoom OAuth and TELEHEALTH_WEBHOOK_URL.

### [2026-03-05] - Refactor - Remove Cursor/non-essential files; trim gcloud upload
* **Removed:** `.cursor/`, `gunicorn.ctl`, diagram-export-*.png, hubspot<>klavyio_telehealth_infra_dose.png, internal-cdp-built.png, mp3-output-ttsfree(dot)com.mp3, document-export-*.md.
* **.gitignore:** Added `.cursor/` so it is not re-committed.
* **.gcloudignore:** Added `docs/`, `__pycache__/` so Cloud Function deploy uploads only runtime-needed files.

### [2026-03-05] - Fix - Replace deprecated google.generativeai with google-genai
* **main.py:** Switched to `from google import genai` and `genai.Client()` / `client.models.generate_content()` (removes FutureWarning in logs).
* **requirements.txt:** Replaced `google-generativeai` with `google-genai`.

### [2026-03-05] - Fix - Zoom transcript webhook delay: document reality and set expectations
* **docs/TROUBLESHOOTING.md:** Documented that Zoom’s `recording.transcript_completed` has no fixed SLA—delays of 15–45+ min (and sometimes hours) are normal; 25+ min with no logs is expected. Added links to Zoom Developer Forum; note to wait 15–30 min before assuming failure, 45–60 min before treating as config issue. Optional future: poll Zoom API after `meeting.ended` for transcript readiness (not implemented).
* **CHANGELOG.md (Architecture):** Noted in Flow 1 that Zoom often sends transcript webhook 15–45+ min after call end, with pointer to TROUBLESHOOTING.

### [2026-03-04] - Fix - Calendly BigQuery insert: event_start/event_end empty string → null
* **functions/calendly/main.py, calendly_webhook.py:** Use `None` for missing/empty `start_time` and `end_time` so BigQuery TIMESTAMP columns get null instead of `''` (fixes "Could not parse '' as a timestamp").

### [2026-03-04] - Feat - Calendly PAT from Secret Manager; script --from-secret-manager
* **scripts/register_calendly_webhook.py:** Added `--from-secret-manager` (and `--project`) to load CALENDLY_PERSONAL_ACCESS_TOKEN from Google Secret Manager when env is not set. Verified token in GSM is valid and webhook registration succeeds.
* **Cloud Function:** Confirmed calendly_webhook_handler has CALENDLY_PERSONAL_ACCESS_TOKEN secret wired (secretEnvironmentVariables). Script and CF both use the same secret.

### [2026-03-04] - Fix - Zoom: add logging for event type and early returns; TROUBLESHOOTING Calendly 403, RudderStack 0
* **main.py:** Log which path is taken (event ignored with event type, no transcript, duration < 5 min, no-show, success to RudderStack) so Cloud Run logs show why no event reached RudderStack.
* **docs/TROUBLESHOOTING.md:** Why GET 400/404 are browser only; how to confirm 0 events via RudderStack MCP; Calendly GET 403 fix (allow public access on Cloud Run).

### [2026-03-03] - Fix - Calendly deploy from functions/calendly only; troubleshooting doc
* **Added:** `scripts/deploy_calendly_webhook.sh` — Deploys Calendly webhook from `functions/calendly` only (avoids loading Zoom main.py/genai and container crash).
* **Added:** `docs/TROUBLESHOOTING.md` — Why Calendly showed main.py/genai and crashed; why RudderStack can show 0 events; fix steps and checklist.

### [2026-03-03] - Feat - Deploy script for Zoom telehealth Cloud Function
* **Added:** `scripts/deploy_zoom_webhook.sh` — Deploys `main.py` to Cloud Function `zoom-telehealth-automation` (Gen2, us-central1). Uses secrets ZOOM_SECRET_TOKEN, RUDDERSTACK_URL, RUDDERSTACK_WRITE_KEY. Run after `gcloud auth login` and `gcloud config set project dosedaily-raw`.

### [2026-03-03] - Feat - Zoom test script and TTS recommendations
* **Added:** `docs/ZOOM_TEST_SCRIPT.md` — Script to play during a Zoom test call (includes "Summary for the email:" for pipeline extraction, >50 words, 5+ min note). Free TTS tools: Natural Reader, Google Translate, macOS Speak, Windows Narrator, Balabolka, TTSFree.com.

### [2026-03-03] - Feat - Klaviyo post-call email setup doc
* **Added:** `docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md` — Step-by-step: create metric (Telehealth_Call_Finished), flow trigger, email template with `{{ event.kims_custom_note }}`, identity resolution (userId = patient email), and end-to-end test checklist.

### [2026-03-03] - Feat - Local dev setup: venv, run scripts, .env.example
* **Added:** Virtual env `tel_env` (per principal-data-engineer naming: first 3 letters of project).
* **Added:** `google-cloud-bigquery` to `requirements.txt` (required by `calendly_webhook.py`).
* **Added:** `.gitignore` for venv, `.env`, `__pycache__`.
* **Added:** `.env.example` — Documents env vars for Zoom (ZOOM_SECRET_TOKEN, RUDDERSTACK_URL, RUDDERSTACK_WRITE_KEY), Calendly (CALENDLY_PERSONAL_ACCESS_TOKEN), GCP (GCP_PROJECT), Gemini (GEMINI_API_KEY).
* **Git:** Initialized git repository.
* **Local run:** Zoom webhook on port 8080, Calendly webhook on port 8081. Use:
  - `source tel_env/bin/activate`
  - `functions-framework --target=telehealth_webhook_handler --source=main.py --port=8080`
  - `functions-framework --target=calendly_webhook_handler --source=calendly_webhook.py --port=8081`

### [2026-03-30] - Docs - Nutritionist manual: vertical Mermaid flowchart
* **docs/NUTRITIONIST_INSTRUCTION_MANUAL.md:** “Big picture” diagram switched from `flowchart LR` to **`flowchart TD`** with stacked steps and `J --> K` linking form submit to follow-up email. Slack-reminder section diagram replaced fan-out diamond with a **single vertical chain** (Name/Email → time → Zoom → Form → what to do). “After the call” form-steps diagram switched from **LR** to **TD** inside a subgraph for narrow viewers.

### [2026-03-30] - Docs - Align Kim manual, quick reference, technical plan with CHANGELOG
* **docs/KIM_QUICK_REFERENCE.md:** Updated for Slack Name/Email reminder, form defaults and duration rules (5 min form / 10 min Zoom no-show split), canonical **email/name** event fields, **linebreaksbr** for Klaviyo notes, product routing pointers.
* **docs/NUTRITIONIST_INSTRUCTION_MANUAL.md:** Same operational reality; Slack section shows Name + Email; optional duration/product; troubleshooting includes Klaviyo skip/template note; pointer to Slack separation + Klaviyo docs.
* **docs/TELEHEALTH_WORKFLOW_PLAN.md:** Replaced obsolete `recording.transcript_completed`-first plan with **current** architecture: form-first Klaviyo path, **meeting.ended** idempotency and Firestore, **Telehealth_Call_No_Show** &lt;10 min, **SLACK_WEBHOOK_URL_TELEHEALTH**, `process_transcript` not wired to HTTP handler, Mermaid + verification table aligned to `main.py` + CHANGELOG.

### [2026-03-30] - Fix - Klaviyo docs: use linebreaksbr not nl2br
* **docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md, main.py (comments):** Klaviyo does not support `nl2br`; it triggers **Email Syntax Error**. Correct Django-style filters are **`linebreaksbr`** or **`newline_to_br`** ([Klaviyo filter glossary](https://developers.klaviyo.com/en/docs/glossary_of_variable_filters)).

### [2026-03-27] - Fix - Calendly reminder Slack: Name vs Email fields
* **functions/calendly_reminder/main.py:** Slack attachment **Name** field now shows **invitee_name** (not invitee_email). Added **Email** field for invitee_email.

### [2026-03-27] - Feat - Telehealth event: email/name only; Kim note as bullets for Klaviyo
* **main.py:** `Telehealth_Call_Finished` (form path) track properties no longer include duplicate `patient_email` / `patient_name`; canonical fields are **`email`** and **`name`**. `kims_custom_note` is normalized to newline-separated **`•`** lines (parses `1. … 2. …` on one line or multiple lines). Zoom/transcript path uses the same bullet helper for `kims_custom_note`. **Breaking:** Downstream jobs or Klaviyo merge tags that referenced `event.patient_email` / `event.patient_name` must switch to `event.email` / `event.name`.
* **docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md:** Event shape, merge-tag guidance (**linebreaksbr** for HTML), webhook JSON body uses `name`; Part **7.3** — webhook after each split vs single webhook.
* **functions/klaviyo_email_sent/main.py:** Webhook body accepts **`name`** (preferred) or `patient_name`.

### [2026-03-27] - Fix - Klaviyo email-sent deploy: org policy workaround and docs
* **scripts/deploy_klaviyo_email_sent.sh:** Support `KLAVIYO_DEPLOY_NO_PUBLIC_IAM=1` to deploy with `--no-allow-unauthenticated` when org policy blocks public `run.invoker` for `allUsers`; documented inline. Default remains `--allow-unauthenticated` for Klaviyo flow webhooks.
* **docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md (Part 7):** Troubleshooting for deploy error “permitted customer” / organization policy; options (admin exception, deploy without public IAM then Console, Console redeploy with `SLACK_WEBHOOK_URL_TELEHEALTH`).

---

## 🚀 Next Steps (For Cursor / AI Assistant)
1.  **Identity Resolution:** Write documentation or SQL for RudderStack to accurately map the Zoom `meeting_uuid` back to the Calendly `user_email` so Klaviyo receives the correct identifier.
2.  **Calendly Webhook:** Draft the API request to subscribe our RudderStack endpoint to Calendly's `invitee.created` and `invitee.canceled` events.
3.  **BigQuery Schema:** Define the SQL table schema for the `Telehealth_Call_Finished` events.
4.  **Reverse ETL SQL:** Write the RudderStack SQL query to extract non-patients for the Klaviyo invite segment.