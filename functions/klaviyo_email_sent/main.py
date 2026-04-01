"""
Klaviyo flow webhook callback: when the post-call follow-up email is sent, Klaviyo POSTs here.
We post a short confirmation to Slack (e.g. "Follow-up email sent to customer@example.com").
Requires: SLACK_WEBHOOK_URL at runtime (prefer GSM SLACK_WEBHOOK_URL_TELEHEALTH; see docs/SLACK_WEBHOOK_SEPARATION.md).
Optional: KLAVIYO_CALLBACK_SECRET (header X-Klaviyo-Callback-Secret).
"""
import logging
import os

import requests
import functions_framework

SLACK_WEBHOOK_URL = (os.environ.get("SLACK_WEBHOOK_URL", "") or "").strip()
KLAVIYO_CALLBACK_SECRET = (os.environ.get("KLAVIYO_CALLBACK_SECRET", "") or "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _send_slack(text: str) -> bool:
    if not SLACK_WEBHOOK_URL:
        return False
    try:
        r = requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": text},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        return r.ok
    except Exception as e:
        logger.warning("Slack post failed: %s", e)
        return False


@functions_framework.http
def klaviyo_email_sent_handler(request):
    """
    Accept POST from Klaviyo flow webhook (placed after "Send Email").
    Body (JSON): email (required), name or patient_name (optional).
    Optional header: X-Klaviyo-Callback-Secret must match KLAVIYO_CALLBACK_SECRET if set.
    """
    if request.method != "POST":
        return ("Method not allowed", 405)

    if KLAVIYO_CALLBACK_SECRET:
        secret = request.headers.get("X-Klaviyo-Callback-Secret", "").strip()
        if secret != KLAVIYO_CALLBACK_SECRET:
            logger.warning("Klaviyo callback: invalid or missing secret")
            return ("Unauthorized", 401)

    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set")
        return ("OK", 200)

    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}

    email = (body.get("email") or "").strip()
    if not email:
        logger.warning("Klaviyo callback: missing email in body")
        return ("Missing email", 400)

    patient_name = (body.get("name") or body.get("patient_name") or "").strip()
    if patient_name:
        text = f"Follow-up email sent to {patient_name} ({email})"
    else:
        text = f"Follow-up email sent to {email}"

    if _send_slack(text):
        logger.info("Slack notified: follow-up sent to %s", email)
        return ("OK", 200)
    return ("Slack delivery failed", 500)
