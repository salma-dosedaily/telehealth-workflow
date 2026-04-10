# Zoom fast path: follow-up email in ~5–15 minutes

**If Server-to-Server OAuth is not available** for your Zoom account, use a **General App** with a one-time user authorization (see **Alternative: General App** below).

The pipeline uses only **meeting.ended + poll**: Zoom sends `meeting.ended` ~1 min after the call; the function polls Zoom's recordings API every 2 min until the transcript is ready (~5–15 min), then runs the pipeline. You need Zoom API access via either: **(A) Server-to-Server OAuth app**, or **(B) General App (OAuth 2.0) with a stored refresh token**.

## How it works

1. **Zoom** sends `meeting.ended` within about a minute of the call ending.
2. The Cloud Function **returns 200 immediately** and enqueues a **Cloud Task** to run in 2 minutes.
3. The task **polls Zoom’s API** (Server-to-Server OAuth) for recording files. When a `TRANSCRIPT` file appears, it **downloads** it and runs the same pipeline (no-show check, extract nutritionist summary, send to RudderStack/Klaviyo).
4. If the transcript is not ready yet, it **re-enqueues** another task in 2 minutes (up to 20 attempts ≈ 40 minutes), then gives up.

So you get the event as soon as Zoom has the transcript (often 5–15 min), instead of waiting for their delayed webhook.

## What you need

- **Zoom app** with **Event subscription** for **Meeting → Meeting ended** (`meeting.ended`). No other Zoom events are required.
- **Zoom Server-to-Server OAuth app** (same or different app) with:
  - **Scopes:** e.g. `recording:read:admin` or `recording:read` (and account access to cloud recordings).
  - **Credentials:** Account ID, Client ID, Client Secret (from Zoom Marketplace).
- **Google Cloud Tasks queue** and env/secret config for the Cloud Function.

## 1. Create the Cloud Tasks queue and POLL_SECRET (GCP)

Run the setup script once (enables Cloud Tasks API, creates queue and POLL_SECRET in GSM, grants the function’s SA access):

```bash
./scripts/setup_gcp_fast_path.sh
```

Or manually create the queue only:

```bash
gcloud tasks queues create telehealth-poll \
  --location=us-central1 \
  --project=dosedaily-raw
```

## 2a. Zoom Server-to-Server OAuth app (if available)

1. In [Zoom Marketplace](https://marketplace.zoom.us/) create (or use) a **Server-to-Server OAuth** app.
2. Add scopes: **View cloud recordings** (e.g. `recording:read` or `recording:read:admin`).
3. Copy **Account ID**, **Client ID**, **Client Secret**.

Store them in **Google Secret Manager** (recommended) or set as env vars:

- `ZOOM_ACCOUNT_ID`
- `ZOOM_CLIENT_ID`
- `ZOOM_CLIENT_SECRET`

## 2b. Alternative: General App (OAuth 2.0) when S2S is not available

If your account cannot create a Server-to-Server OAuth app, use a **General App** and a **one-time user authorization** so the Cloud Function can poll the recordings API with a refresh token.

1. In [Zoom Marketplace](https://marketplace.zoom.us/) click **Build App** and choose **General App**.
2. **App credentials:** copy **Client ID** and **Client Secret**.
3. **Redirect URL:** Zoom requires **HTTPS**. Deploy the OAuth callback (step 6), then add the printed URL (e.g. `https://zoom-oauth-callback-xxx.run.app/callback`) to your app’s redirect allow list.
4. **Scopes:** add **recording:read** (View cloud recordings for the authorized user).
5. **Activate** the app.
6. **Get the refresh token (HTTPS):**
   - **Option A – Deploy callback to Cloud Run:** Run `./scripts/deploy_zoom_oauth_callback.sh` (with `ZOOM_CLIENT_ID` and `ZOOM_CLIENT_SECRET` set). Add the printed Redirect URL to Zoom, then open the function URL in a browser and complete auth. If you get *"One or more users named in the policy do not belong to a permitted customer"*, your org policy blocks public Cloud Run — use Option B.
   - **Option B – ngrok (when org policy blocks public Cloud Run):** Install [ngrok](https://ngrok.com/). In one terminal run `ngrok http 8765` and copy the HTTPS URL (e.g. `https://abc123.ngrok-free.app`). In Zoom, add `https://YOUR-NGROK-URL/callback` to the redirect allow list. In another terminal run:
     ```bash
     export ZOOM_CLIENT_ID=your_id ZOOM_CLIENT_SECRET=your_secret
     python scripts/zoom_oauth_authorize.py --redirect-uri https://YOUR-NGROK-URL/callback --project dosedaily-raw
     ```
     Open the printed authorize URL in a browser; after Zoom redirects, the script receives the code and stores the refresh token in GSM.
7. In GCP, ensure the Cloud Function has:
   - **Secret Manager Secret Accessor** on `ZOOM_REFRESH_TOKEN` (to read the token).
   - **Secret Manager Secret Version Adder** on `ZOOM_REFRESH_TOKEN` (so the function can save Zoom’s new refresh token after each use; Zoom invalidates the old one).
   ```bash
   PROJECT=dosedaily-raw
   PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
   SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
   gcloud secrets add-iam-policy-binding ZOOM_REFRESH_TOKEN --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor --project=$PROJECT
   gcloud secrets add-iam-policy-binding ZOOM_REFRESH_TOKEN --member="serviceAccount:${SA}" --role=roles/secretmanager.secretVersionAdder --project=$PROJECT
   ```
8. Deploy the Zoom webhook with **ZOOM_REFRESH_TOKEN** and **ZOOM_CLIENT_ID**, **ZOOM_CLIENT_SECRET** from Secret Manager (no `ZOOM_ACCOUNT_ID`). The fast path will use the refresh token to get access tokens and poll for the transcript.

## 3. Configure the Cloud Function

After deploying the Zoom webhook, get its URL:

```bash
gcloud functions describe telehealth_webhook_handler --gen2 --region=us-central1 --project=dosedaily-raw --format='value(serviceConfig.uri)'
```

Set the following (env vars or Secret Manager, then redeploy / set on Cloud Run):

| Variable | Description |
|----------|-------------|
| `TELEHEALTH_WEBHOOK_URL` | The Cloud Function URL (same as above). |
| `POLL_SECRET` | A random secret string. The poll task sends this in `X-Poll-Secret` so the function accepts internal poll requests. |
| `GCP_PROJECT` | e.g. `dosedaily-raw`. |
| `GCP_REGION` | e.g. `us-central1`. |
| `TASKS_QUEUE` | `telehealth-poll`. |
| `ZOOM_ACCOUNT_ID` | From Zoom S2S OAuth app. |
| `ZOOM_CLIENT_ID` | From Zoom S2S OAuth app. |
| `ZOOM_CLIENT_SECRET` | From Zoom S2S OAuth app. |

Example deploy with env (replace values):

```bash
gcloud functions deploy telehealth_webhook_handler \
  --gen2 --runtime=python312 --region=us-central1 --source=. \
  --entry-point=telehealth_webhook_handler --trigger-http --no-allow-unauthenticated \
  --set-secrets=ZOOM_SECRET_TOKEN=ZOOM_SECRET_TOKEN:latest,RUDDERSTACK_URL=RUDDERSTACK_URL:latest,RUDDERSTACK_WRITE_KEY=RUDDERSTACK_WRITE_KEY:latest \
  --set-env-vars="GCP_PROJECT=dosedaily-raw,GCP_REGION=us-central1,TASKS_QUEUE=telehealth-poll,TELEHEALTH_WEBHOOK_URL=https://YOUR-CLOUD-RUN-URL.run.app,POLL_SECRET=your_random_secret,ZOOM_ACCOUNT_ID=xxx,ZOOM_CLIENT_ID=xxx,ZOOM_CLIENT_SECRET=xxx" \
  --project=dosedaily-raw
```

(Prefer storing `POLL_SECRET` and Zoom OAuth values in Secret Manager and using `--set-secrets` if your org requires it.)

## 4. Allow Cloud Tasks to invoke the function

The poll task sends an HTTP POST to `TELEHEALTH_WEBHOOK_URL`. Either:

- **Option A:** In Cloud Run → **telehealth-webhook-handler** → **Security** → **Allow public access** (the handler still checks `X-Poll-Secret` for poll requests), or  
- **Option B:** Keep the function private and grant the **Cloud Tasks service account** (e.g. `PROJECT_NUMBER-compute@developer.gserviceaccount.com`) the **Cloud Run Invoker** role, and create tasks with an **OIDC token** for that service account (see Cloud Tasks docs).

## 5. Subscribe Zoom to meeting.ended

In **Zoom Developer** → your webhook app → **Event subscription**:

- **Subscribe to:** **Meeting** → **Meeting ended** (`meeting.ended`).
- **Event notification endpoint URL:** same as `TELEHEALTH_WEBHOOK_URL` (the Cloud Function URL).
- **Secret Token:** same as `ZOOM_SECRET_TOKEN` in GCP.

You can keep **Recording → Transcript completed** subscribed as a fallback.

## Summary-only mode (faster Klaviyo email)

The pipeline supports **summary-only** mode: only the nutritionist’s note is extracted (regex + optional Gemini if regex misses). Sentiment and internal summary are skipped so the handler finishes faster.

- **Env:** `SUMMARY_ONLY=True` (default). Set `SUMMARY_ONLY=False` if you want full Gemini sentiment + summary again.

