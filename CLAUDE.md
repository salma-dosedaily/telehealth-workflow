# Project Context: Lean Telehealth Automation

## 📖 Project Overview
We are building a fully automated, "Lean" Telehealth data pipeline. The primary goal is to completely bypass expensive CRM routing (e.g., HubSpot Professional / Salesforce) by utilizing a "Warehouse-First" architecture and custom Google Cloud Functions. The system captures patient bookings, processes post-consultation notes using AI, and routes data to our Data Warehouse and Marketing Platform.

## 🏗️ Architecture & Tech Stack
* **Logic Engine:** Google Cloud Function (Python 3.10+) + Gemini 2.5 API.
* **Intake:** Calendly (Teams Tier - API Enabled).
* **Consultation:** Zoom (Pro/Business Tier - Cloud Recording & Transcripts Enabled).
* **CDP / Router:** RudderStack.
* **Data Warehouse:** Google BigQuery.
* **Marketing Automation:** Klaviyo.
* **Database / State:** Google Firestore (used for storing `meeting.ended` events and prefilled form URLs).

## 🔄 Core Data Flows

### Flow 1: Active Patient Post-Call Lifecycle
1. A patient books via Calendly, which syncs to BigQuery/RudderStack.
2. The patient and Nutritionist (Kim) meet on Zoom.
3. When the call ends, Zoom sends a `meeting.ended` webhook. 
4. The system executes a "Fast Path" using Zoom OAuth (Refresh Token) to poll the Zoom API for the transcript every 2 minutes.
5. The Cloud Function executes the main logic: it downloads the `.vtt` transcript, runs a No-Show Safety Check (halts if the transcript is < 50 words or duration is < 10 minutes), and passes the transcript to the Gemini API.
6. Gemini extracts sentiment, an internal summary, and voice-dictated notes (`kims_custom_note`).
7. The Cloud Function constructs a JSON payload and sends it to RudderStack.
8. RudderStack routes the raw data to BigQuery and triggers a `Telehealth_Call_Finished` event to Klaviyo to send a post-call email populated with the AI notes.

### Flow 2: Bulk Acquisition / Lead Invites (Reverse ETL)
1. BigQuery acts as the Single Source of Truth.
2. RudderStack runs SQL queries against BigQuery to identify contacts where `is_active_patient = FALSE`.
3. RudderStack syncs these contacts into a Klaviyo Segment, triggering a "Nutrition Program Invite" campaign.

## 📝 Active Development Constraints & Rules

### Event Naming & Properties
* **Klaviyo Canonical Fields:** Use `email` and `name` as the primary identifiers for Klaviyo events, replacing older duplicates like `patient_email` or `patient_name`.
* **Product Routing:** Ensure `productName` is synced to Klaviyo profiles as a trait (`telehealth_product`, `telehealth_last_product`) to allow for conditional splits based on "Liver", "Cholesterol", or "Bundle".
* **No-Shows:** Calls lasting under 10 minutes must trigger a `Telehealth_Call_No_Show` event rather than a completed event.

### Text Formatting 
* **Kim's Notes:** `kims_custom_note` must normalize line endings to newline-separated `•` bullet points for Klaviyo compatibility.
* **Klaviyo Line Breaks:** Always use the `linebreaksbr` or `newline_to_br` filters in Klaviyo templates; do not use `nl2br` as it causes syntax errors.

### Infrastructure & Security
* **Slack Webhooks:** Strict separation must be maintained between `SLACK_WEBHOOK_URL_TELEHEALTH` (for 15-min reminders and Klaviyo callbacks) and `SLACK_WEBHOOK_URL` (for ETL jobs).
* **Authentication:** Always prioritize identifying users in RudderStack (`userId` = patient email) prior to sending track events so Klaviyo flows do not skip due to missing profiles.
* **Service Accounts:** Cross-project queries (e.g., Cursor MCP) require the `mcp-bigquery-cross` service account to interact with both `dosedaily-raw` and `dosedaily-prod`.

## 🚀 Current Immediate Next Steps
1. Document or map RudderStack SQL to connect Zoom `meeting_uuid` to Calendly `user_email`.
2. Draft API requests for Calendly `invitee.created` and `invitee.canceled` webhook subscriptions.
3. Define the BigQuery SQL schema for `Telehealth_Call_Finished` events.
4. Write the RudderStack Reverse ETL query for non-patients.