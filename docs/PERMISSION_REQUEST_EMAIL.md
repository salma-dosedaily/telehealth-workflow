# Permission Request — Live Test Credentials

**Use this draft to request the credentials and access needed for the telehealth automation live test. Send from or on behalf of the data/engineering team to the stakeholder who controls Zoom, Calendly, and/or account admin.**

---

**Subject:** Credentials & permissions for Telehealth automation live test (Zoom, Calendly, data@dosedaily.co)

Hi [Stakeholder name],

We’re ready to run a live test of the Telehealth automation (post-call notes → BigQuery → Klaviyo via RudderStack). To finish wiring the pipeline, we need the following permissions and credentials **for the service account data@dosedaily.co** (or the account you use for automation):

---

**1. Zoom (Pro/Business)**  
- **Admin access** (or equivalent) to the Zoom account used for patient consultations.  
- **Enable:** Cloud Recording and **Audio Transcripts** for the meetings that should trigger the workflow.  
- **App/Webhook:** Create (or use an existing) Zoom app with **Server-to-Server OAuth** or **Webhook-only** subscription to:  
  - **Event:** Recording → **Transcript completed**.  
- **Credentials to provide:**  
  - **Webhook Secret Token** (for endpoint validation).  
  - If we need to call Zoom APIs (e.g. participant list): **Account ID**, **Client ID**, **Client Secret** (stored in Google Secret Manager only).

---

**2. Calendly (Teams tier)**  
- **API / Personal Access Token** for **data@dosedaily.co** (or the Calendly account that receives the bookings).  
- We use this to sync bookings to BigQuery/RudderStack so we can map Zoom meetings to patient email for Klaviyo.  
- **Scope:** Read access to scheduled events and invitee details (e.g. invitee.created, invitee.canceled, and event types used for these consultations).

---

**3. Confirm service account**  
- Confirm that **data@dosedaily.co** is the correct identity for:  
  - Running the Cloud Function (Zoom webhook).  
  - Accessing secrets in Google Secret Manager (Zoom token, Calendly token, RudderStack URL, Gemini API key if used).  
- If a different service account or user is required for Calendly API, please specify.

---

**4. RudderStack & Klaviyo**  
- We already have (or will configure) the RudderStack webhook URL and Klaviyo connection. No additional credentials from you unless you control those; if so, please share the **RudderStack Webhook URL** (and any write key) for the Telehealth source.

---

Please reply with:  
- Confirmation that Zoom Cloud Recording + Audio Transcripts and the webhook app can be enabled,  
- The Zoom webhook secret token (or instructions to retrieve it from the Zoom Developer app),  
- The Calendly API/Personal Access Token for data@dosedaily.co (or the designated account),  
- Any constraints (e.g. only certain event types or Zoom users in scope).

We’ll store all tokens in Google Secret Manager and use them only from the Cloud Function. No credentials will be committed to code or shared over unsecured channels.

Thanks,  
[Your name]
