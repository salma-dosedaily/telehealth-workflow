"""
Calendly webhook handler: receives invitee.created / invitee.canceled,
fetches invitee details via Calendly API, writes to BigQuery.
Webhook subscription is created via Calendly API (run scripts/register_calendly_webhook.py after deploy).
"""
import os
import re
import json
import logging
import requests
import functions_framework
from google.cloud import bigquery

# Load env vars (secrets from GSM when deployed)
CALENDLY_PAT = os.environ.get("CALENDLY_PERSONAL_ACCESS_TOKEN", "")
BQ_PROJECT = os.environ.get("GCP_PROJECT", "dosedaily-raw")
BQ_DATASET = "telehealth"
BQ_TABLE = "calendly_bookings"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _parse_invitee_uri(uri: str) -> tuple[str | None, str | None]:
    """Extract event_uuid and invitee_uuid from Calendly invitee URI."""
    if not uri:
        return None, None
    # URI format: https://api.calendly.com/scheduled_events/{event_uuid}/invitees/{invitee_uuid}
    match = re.search(
        r"scheduled_events/([^/]+)/invitees/([^/?#]+)",
        uri,
    )
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _fetch_invitee(event_uuid: str, invitee_uuid: str, token: str) -> dict | None:
    """Fetch invitee details from Calendly API."""
    if not token:
        logger.warning("CALENDLY_PERSONAL_ACCESS_TOKEN not set")
        return None
    url = f"https://api.calendly.com/scheduled_events/{event_uuid}/invitees/{invitee_uuid}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Calendly API fetch failed: %s", e)
        return None


def _insert_into_bigquery(rows: list[dict]) -> None:
    """Insert rows into telehealth.calendly_bookings."""
    if not rows:
        return
    client = bigquery.Client(project=BQ_PROJECT)
    table_ref = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        logger.error("BigQuery insert errors: %s", errors)
        raise RuntimeError(f"BigQuery insert failed: {errors}")


@functions_framework.http
def calendly_webhook_handler(request):
    """
    HTTP handler for Calendly webhooks (invitee.created, invitee.canceled).
    Parses payload, fetches invitee details via API, writes to BigQuery.
    """
    if request.method != "POST":
        return ("Method not allowed", 405)

    try:
        payload = request.get_json()
    except Exception:
        return ("Invalid JSON", 400)

    event_type = payload.get("event")
    payload_data = payload.get("payload", {})

    # Get invitee URI (Calendly sends uri in payload)
    invitee_uri = payload_data.get("uri") or ""
    if isinstance(invitee_uri, dict):
        invitee_uri = invitee_uri.get("uri", "")

    event_uuid, invitee_uuid = _parse_invitee_uri(invitee_uri or "")

    if not event_uuid or not invitee_uuid:
        logger.warning("Could not parse invitee URI from payload: %s", json.dumps(payload)[:500])
        return ("OK", 200)  # Accept to avoid retries

    # Fetch full invitee details from Calendly API
    invitee_data = _fetch_invitee(event_uuid, invitee_uuid, CALENDLY_PAT)
    if not invitee_data:
        return ("OK", 200)

    resource = invitee_data.get("resource", {})
    event_data = resource.get("event", "")
    # BigQuery TIMESTAMP rejects empty string; use None for null
    event_start = resource.get("start_time") or None
    event_end = resource.get("end_time") or None
    invitee_email = resource.get("email", "")
    invitee_name = resource.get("name", "")
    status = resource.get("status", "active")
    canceled = payload_data.get("canceled", False)
    rescheduled = payload_data.get("rescheduled", False)

    # Fetch event details if event_data is a URI (some payloads include event object)
    host_email = ""
    event_name = ""
    if isinstance(event_data, str) and "scheduled_events" in event_data:
        try:
            ev_resp = requests.get(
                event_data,
                headers={"Authorization": f"Bearer {CALENDLY_PAT}", "Content-Type": "application/json"},
                timeout=10,
            )
            if ev_resp.ok:
                ev_json = ev_resp.json()
                ev_resource = ev_json.get("resource", {})
                event_name = ev_resource.get("name", "")
                host_uri = ev_resource.get("event_memberships", [{}])[0].get("user", "")
                if host_uri:
                    u_resp = requests.get(
                        host_uri,
                        headers={"Authorization": f"Bearer {CALENDLY_PAT}", "Content-Type": "application/json"},
                        timeout=10,
                    )
                    if u_resp.ok:
                        host_email = u_resp.json().get("resource", {}).get("email", "")
        except Exception as e:
            logger.warning("Could not fetch event/host details: %s", e)

    row = {
        "event_type": event_type,
        "invitee_uri": invitee_uri,
        "invitee_email": invitee_email,
        "invitee_name": invitee_name,
        "event_uuid": event_uuid,
        "invitee_uuid": invitee_uuid,
        "event_start": event_start,
        "event_end": event_end,
        "event_name": event_name,
        "host_email": host_email,
        "status": status,
        "canceled": canceled,
        "rescheduled": rescheduled,
    }

    try:
        _insert_into_bigquery([row])
    except Exception as e:
        logger.error("BigQuery insert failed: %s", e)
        return ("Internal error", 500)

    return ("OK", 200)
