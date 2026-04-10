# Slack: separate Telehealth vs ETL webhooks

## Problem

If **one** Secret Manager secret `SLACK_WEBHOOK_URL` is shared by **telehealth** (Calendly reminder, Klaviyo callback) and **ETL / data jobs**, updating it for telehealth makes **ETL post into `#telehealth-calls`** (or the opposite).

Slack **Incoming Webhooks** are **one URL → one channel**. You need **two webhooks** and **two secrets**.

## Fix (two secrets)

| Secret (GSM) | Webhook posts to | Used by |
|--------------|------------------|---------|
| `SLACK_WEBHOOK_URL_TELEHEALTH` | Telehealth channel (e.g. `#telehealth-calls`) | `calendly_reminder_handler`, `klaviyo_email_sent_handler` |
| `SLACK_WEBHOOK_URL` | ETL / data alerts channel | Composer, Dataflow, scripts, etc. |

## Apply in one command

```bash
cd /path/to/telehealth-workflow
export GCP_PROJECT=dosedaily-raw GCP_REGION=us-central1 FIRESTORE_DATABASE_ID=telemeetinglog
export TELEHEALTH_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/.../telehealth...'
export ETL_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/.../etl...'
./scripts/apply_slack_webhook_separation_fix.sh
```

Get each URL from **Slack → Apps → Incoming Webhooks** (or your integration settings). **Post to channel** must match the channel you want for that integration.

## Or step by step

1. `TELEHEALTH_SLACK_WEBHOOK_URL=... ./scripts/setup_slack_webhook_telehealth_secret.sh`
2. `ETL_SLACK_WEBHOOK_URL=... ./scripts/restore_etl_slack_webhook.sh`
3. `./scripts/deploy_calendly_reminder.sh`
4. `./scripts/deploy_klaviyo_email_sent.sh`

## Regenerating a Slack URL

**Regenerate** only invalidates the old token; the new URL still posts to the **same** channel selected in the integration. It does **not** move traffic between telehealth and ETL. Use **two integrations** / **two channels** instead.

## IAM

`setup_slack_webhook_telehealth_secret.sh` grants `roles/secretmanager.secretAccessor` on `SLACK_WEBHOOK_URL_TELEHEALTH` to the default compute service account (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`). If functions use a custom SA, grant that SA the same role on the secret.
