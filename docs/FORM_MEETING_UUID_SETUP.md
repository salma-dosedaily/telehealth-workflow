# Google Form + Meeting UUID + FORM_SUBMIT_SECRET

This doc covers:

1. **Meeting UUID** — Optional form field so Kim can paste the Zoom meeting UUID; the Cloud Function then looks up the meeting in Firestore and adds `host_email` and `meeting_date` to the RudderStack event.
2. **Firestore** — Must be enabled when using Meeting UUID (the function stores `meeting.ended` and looks up by UUID on form submit).
3. **FORM_SUBMIT_SECRET** — Secret in GSM and in the form script so only your form can call the endpoint.

---

## 1. Ensure Firestore is enabled (required for Meeting UUID)

When the form includes a **Meeting UUID**, the function:

- On **Zoom `meeting.ended`**: writes meeting data (uuid, host_email, duration, start_time) to Firestore collection `telehealth_meetings_ended`.
- On **form submit** with `meeting_uuid`: looks up that document and merges `host_email` and `meeting_date` into the event sent to RudderStack/Klaviyo.

If Firestore is not enabled or the function’s service account lacks permission, the form still works but the event will not get `host_email` / `meeting_date` when a UUID is provided.

**One-time setup:** run the script that enables Firestore and creates `FORM_SUBMIT_SECRET`:

```bash
./scripts/setup_firestore_form_secret.sh
```

This script:

- Enables **Firestore API** (`firestore.googleapis.com`).
- **Creates the Firestore (default) database** in your chosen region if it does not exist. (Enabling the API alone is not enough; the database must be created once.)
- Grants the default compute service account **roles/datastore.user** on the project so the Cloud Function can read/write Firestore.
- Creates **FORM_SUBMIT_SECRET** in Google Secret Manager (random value), tags it, and grants the compute SA `secretAccessor`.

After running, it prints the secret value once. Copy it for step 5.

---

## 2. (Optional) Prefill Patient Email and Name from Calendly

When a patient books via Calendly, you can have the form open with **Patient Email** and **Patient Name** already filled so Kim only fills her note, duration, and Meeting UUID. The Calendly webhook builds a prefilled URL and stores it in BigQuery.

- **Setup:** See **docs/CALENDLY_PREFILL_FORM.md** (entry IDs, env vars, BigQuery column, deploy).
- **Meeting UUID** is not available at booking time (it comes from Zoom after the call); Kim pastes it when submitting the form.

---

## 3. Add "Meeting UUID" to the form

In the Google Form, add a **short answer** field titled **Meeting UUID** (optional). Kim can paste either:

- The **Zoom meeting UUID** (the value Zoom uses in webhooks), or  
- The **Zoom join link** (e.g. `https://us06web.zoom.us/j/89166792057?pwd=...`).

The form script extracts the numeric meeting ID from join URLs; the backend looks up the meeting in Firestore by UUID or by that ID and adds `host_email` and `meeting_date` to the event.

---

## 4. FORM_SUBMIT_SECRET in GSM and function env

The same script above creates **FORM_SUBMIT_SECRET** in GSM. To wire it into the Cloud Function:

1. **Redeploy** the webhook (deploy script already wires `FORM_SUBMIT_SECRET` from GSM when the secret exists):

   ```bash
   ./scripts/deploy_zoom_webhook.sh
   ```

2. The function reads `FORM_SUBMIT_SECRET` from its environment (injected from GSM). If set, it **requires** the `X-Form-Secret` header (or `form_secret` in JSON body) to match; otherwise it returns 401.

---

## 5. Set the same secret in the form script

In **Google Apps Script** (Form → Extensions → Apps Script), set the **same** value you got from step 1:

```javascript
const FORM_SUBMIT_SECRET = "paste_the_value_from_setup_script_here";
```

If you leave it empty (`""`), the function will accept form submissions without the header only when it has no `FORM_SUBMIT_SECRET` in its env (not recommended for production).

---

## Summary

| Step | Action |
|------|--------|
| Firestore + secret | Run `./scripts/setup_firestore_form_secret.sh` once |
| Deploy | Run `./scripts/deploy_zoom_webhook.sh` (wires FORM_SUBMIT_SECRET when present) |
| Form field | Add optional short-answer “Meeting UUID” |
| Form script | Set `FORM_SUBMIT_SECRET` to the same value as in GSM |

Result: only your form can call the endpoint (shared secret), and when Kim fills Meeting UUID, the event includes `host_email` and `meeting_date` from the Zoom meeting stored in Firestore.
