"""
Slack 15-min reminder: Cloud Scheduler triggers this every 5 min.
Finds Calendly bookings (event_start in next 15 min), sends Slack message with prefilled form link,
and marks reminder_sent_at so we don't send twice.
Requires: SLACK_WEBHOOK_URL at runtime (from GSM secret SLACK_WEBHOOK_URL_TELEHEALTH via deploy script),
FIRESTORE_DATABASE_ID (same as Calendly), REMINDER_SECRET (optional auth). See docs/SLACK_WEBHOOK_SEPARATION.md.
"""
import os
import logging
from datetime import datetime, timezone, timedelta

import requests
import functions_framework
from google.cloud import firestore

SLACK_WEBHOOK_URL = (os.environ.get("SLACK_WEBHOOK_URL", "") or "").strip()
FIRESTORE_DATABASE_ID = (os.environ.get("FIRESTORE_DATABASE_ID", "") or "").strip() or None
REMINDER_SECRET = (os.environ.get("REMINDER_SECRET", "") or "").strip()
COLLECTION = "calendly_prefilled_forms"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_firestore_client():
    project = os.environ.get("GCP_PROJECT", "dosedaily-raw")
    if FIRESTORE_DATABASE_ID:
        return firestore.Client(project=project, database=FIRESTORE_DATABASE_ID)
    return firestore.Client(project=project)


def _parse_utc(s: str) -> datetime | None:
    """Parse ISO timestamp (e.g. 2026-03-17T13:30:00Z) to UTC datetime."""
    if not s:
        return None
    try:
        s = str(s).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _send_slack(
    prefilled_url: str, invitee_name: str, invitee_email: str, event_start: str,
    zoom_join_url: str = "",
) -> bool:
    if not SLACK_WEBHOOK_URL:
        return False
    patient = invitee_name or invitee_email or "Patient"
    zoom_join_url = (zoom_join_url or "").strip()
    name_display = (invitee_name or "").strip() or "—"
    email_display = (invitee_email or "").strip() or "—"
    fields = [
        {"title": "Name", "value": name_display, "short": True},
        {"title": "Email", "value": email_display, "short": True},
        {"title": "Scheduled", "value": event_start or "—", "short": True},
        {"title": "Form Link", "value": f"<{prefilled_url}|Open prefilled Telehealth Note form>", "short": False},
    ]
    if zoom_join_url:
        fields.insert(-1, {"title": "Zoom Link", "value": f"<{zoom_join_url}|Join Zoom meeting>", "short": False})
    # Short fallback for notifications (no raw URLs); main content is the attachment block with links.
    fallback = f"Reminder: call in ~15 min — {patient}. Zoom and form links in message."
    attachment = {
        "fallback": fallback,
        "color": "#36a64f",
        "pretext": f"*Reminder: call in ~15 min* — {patient}",
        "fields": fields,
        "mrkdwn_in": ["pretext", "fields"],
    }
    # Message is only the attachment block (no raw URLs). Links show as "Join Zoom meeting" / "Open prefilled Telehealth Note form".
    payload = {"attachments": [attachment]}
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        return resp.ok
    except Exception as e:
        logger.warning("Slack send failed: %s", e)
        return False


@functions_framework.http
def calendly_reminder_handler(request):
    """HTTP handler: Cloud Scheduler POSTs every 5 min. Finds bookings in next 15 min, sends Slack, marks sent."""
    if request.method != "POST":
        return ("Method not allowed", 405)
    if REMINDER_SECRET:
        secret = request.headers.get("X-Reminder-Secret", "").strip()
        if secret != REMINDER_SECRET:
            logger.warning("Reminder auth failed: wrong or missing secret")
            return ("Unauthorized", 401)

    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set")
        return ("OK", 200)

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(minutes=20)
    sent = 0

    try:
        client = _get_firestore_client()
        coll = client.collection(COLLECTION)
        for doc in coll.stream():
            data = doc.to_dict()
            if data.get("reminder_sent_at"):
                continue
            event_start_str = data.get("event_start_utc")
            event_dt = _parse_utc(event_start_str)
            if not event_dt:
                continue
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            if event_dt < now or event_dt > window_end:
                continue
            mins_left = (event_dt - now).total_seconds() / 60
            if mins_left > 15.5:
                continue
            prefilled = data.get("prefilled_form_url")
            if not prefilled:
                continue
            zoom_url = (data.get("zoom_join_url") or "").strip()
            if not zoom_url:
                logger.warning(
                    "No zoom_join_url in Firestore for %s (doc %s); Slack reminder will omit Zoom link.",
                    data.get("invitee_email"),
                    doc.id,
                )
            if _send_slack(
                prefilled,
                data.get("invitee_name", ""),
                data.get("invitee_email", ""),
                event_start_str or "",
                zoom_url or "",
            ):
                doc.reference.update({"reminder_sent_at": firestore.SERVER_TIMESTAMP})
                sent += 1
                logger.info("Sent Slack reminder for %s", data.get("invitee_email"))
    except Exception as e:
        logger.error("Reminder run failed: %s", e)
        return ("Internal error", 500)

    return (f"OK (sent {sent})", 200)
