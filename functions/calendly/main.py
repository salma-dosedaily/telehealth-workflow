"""
Calendly webhook handler: receives invitee.created / invitee.canceled,
fetches invitee details via Calendly API, writes to BigQuery.
Optionally builds a prefilled Google Form URL (patient email, name) so Kim only fills notes.
Deploy from functions/calendly. Webhook registration: scripts/register_calendly_webhook.py
"""
import os
import re
import logging
from urllib.parse import quote

import requests
import functions_framework
from google.cloud import bigquery

CALENDLY_PAT = os.environ.get("CALENDLY_PERSONAL_ACCESS_TOKEN", "")
BQ_PROJECT = os.environ.get("GCP_PROJECT", "dosedaily-raw")
BQ_DATASET = "telehealth"
BQ_TABLE = "calendly_bookings"

# Optional: build prefilled form URL (patient email + name). Meeting UUID is not available at booking time.
PREFILL_FORM_BASE_URL = (os.environ.get("PREFILL_FORM_BASE_URL", "") or "").strip()
PREFILL_FORM_ENTRY_EMAIL = (os.environ.get("PREFILL_FORM_ENTRY_EMAIL", "") or "").strip()
PREFILL_FORM_ENTRY_NAME = (os.environ.get("PREFILL_FORM_ENTRY_NAME", "") or "").strip()

# Firestore: same DB as Zoom webhook when FIRESTORE_DATABASE_ID is set (e.g. telemeetinglog). Look up prefilled link by invitee_email.
FIRESTORE_DATABASE_ID = (os.environ.get("FIRESTORE_DATABASE_ID", "") or "").strip() or None
FIRESTORE_COLLECTION_PREFILLED = "calendly_prefilled_forms"

# Email to host (Kim): SendGrid. When someone books, email the prefilled form link to the host.
# SENDGRID_API_KEY from GSM; SENDGRID_FROM_EMAIL = verified sender; HOST_EMAIL = fallback when Calendly host_email is empty
SENDGRID_API_KEY = (os.environ.get("SENDGRID_API_KEY", "") or "").strip()
SENDGRID_FROM_EMAIL = (os.environ.get("SENDGRID_FROM_EMAIL", "") or "").strip()
HOST_EMAIL = (os.environ.get("HOST_EMAIL", "") or "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _str(val) -> str:
    """Return non-None string, stripped; '' if val is None or not string."""
    if val is None:
        return ""
    return str(val).strip() if isinstance(val, (str, int, float)) else ""


# Regex to detect Zoom join URLs (us06web.zoom.us, zoom.us, etc.).
_ZOOM_JOIN_URL_PATTERN = re.compile(
    r"https?://[^\s\"'<>]*zoom\.us/j/[^\s\"'<>]+",
    re.IGNORECASE,
)


def _extract_zoom_join_url(ev_resource: dict) -> str:
    """Extract Zoom join URL from Calendly event location (type zoom or zoom_conference).
    Falls back to location.data.join_url, custom location string, then recursive scan.
    """
    # 1) Standard location object: { "type": "zoom", "join_url": "https://..." }
    loc = ev_resource.get("location")
    if isinstance(loc, dict):
        url = (loc.get("join_url") or "").strip()
        if url and ("zoom" in str(loc.get("type", "")).lower() or "zoom.us" in url):
            return url
        # Some integrations put join_url under location.data
        data = loc.get("data")
        if isinstance(data, dict):
            url = (data.get("join_url") or "").strip()
            if url and "zoom.us" in url:
                return url
    elif isinstance(loc, str):
        # 2) Custom location: plain string that may contain a Zoom link
        match = _ZOOM_JOIN_URL_PATTERN.search(loc)
        if match:
            return match.group(0).strip()

    # 3) locations[] array (alternative API shape)
    locs = ev_resource.get("locations", [])
    for item in (locs if isinstance(locs, list) else []):
        if isinstance(item, dict):
            url = (item.get("join_url") or "").strip()
            if url and ("zoom" in str(item.get("type", "")).lower() or "zoom.us" in url):
                return url
            data = item.get("data")
            if isinstance(data, dict):
                url = (data.get("join_url") or "").strip()
                if url and "zoom.us" in url:
                    return url
        elif isinstance(item, str):
            match = _ZOOM_JOIN_URL_PATTERN.search(item)
            if match:
                return match.group(0).strip()

    # 4) Fallback: scan event resource for any zoom.us/j/ URL (handles odd payloads)
    def _find_zoom_url(obj, depth: int) -> str:
        if depth > 10:
            return ""
        if isinstance(obj, str):
            match = _ZOOM_JOIN_URL_PATTERN.search(obj)
            return match.group(0).strip() if match else ""
        if isinstance(obj, dict):
            for v in obj.values():
                u = _find_zoom_url(v, depth + 1)
                if u:
                    return u
        elif isinstance(obj, list):
            for v in obj:
                u = _find_zoom_url(v, depth + 1)
                if u:
                    return u
        return ""

    return _find_zoom_url(ev_resource, 0)


def _parse_invitee_uri(uri: str) -> tuple:
    """Extract event_uuid and invitee_uuid from Calendly invitee URI."""
    if not uri:
        return None, None
    match = re.search(r"scheduled_events/([^/]+)/invitees/([^/?#]+)", uri)
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


def _build_prefilled_form_url(invitee_email: str, invitee_name: str) -> str | None:
    """Build Google Form prefilled URL with entry.ENTRY_ID=value for email and name.
    Meeting UUID is not available at Calendly booking time; Kim pastes it after the Zoom call.
    """
    if not PREFILL_FORM_BASE_URL or not PREFILL_FORM_ENTRY_EMAIL:
        return None
    base = PREFILL_FORM_BASE_URL.rstrip("/")
    if "?" in base:
        sep = "&"
    else:
        sep = "?"
    params = [f"entry.{PREFILL_FORM_ENTRY_EMAIL}={quote(invitee_email or '', safe='')}"]
    if PREFILL_FORM_ENTRY_NAME:
        params.append(f"entry.{PREFILL_FORM_ENTRY_NAME}={quote(invitee_name or '', safe='')}")
    return base + sep + "&".join(params)


def _get_firestore_client():
    """Lazy Firestore client. Uses (default) unless FIRESTORE_DATABASE_ID is set (e.g. telemeetinglog)."""
    try:
        from google.cloud import firestore
        project = os.environ.get("GCP_PROJECT", BQ_PROJECT)
        if FIRESTORE_DATABASE_ID:
            return firestore.Client(project=project, database=FIRESTORE_DATABASE_ID)
        return firestore.Client(project=project)
    except Exception as e:
        logger.warning("Firestore not available: %s", e)
        return None


def _store_prefilled_link_firestore(
    event_uuid: str,
    invitee_uuid: str,
    invitee_email: str,
    invitee_name: str,
    prefilled_url: str,
    event_start_utc: str | None,
    zoom_join_url: str = "",
) -> None:
    """Store prefilled form URL in Firestore so Kim can look up by invitee_email without querying BigQuery."""
    client = _get_firestore_client()
    if not client:
        return
    try:
        doc_id = f"{event_uuid}_{invitee_uuid}".replace("/", "_")
        coll = client.collection(FIRESTORE_COLLECTION_PREFILLED)
        from google.cloud import firestore
        data = {
            "invitee_email": invitee_email,
            "invitee_name": invitee_name,
            "prefilled_form_url": prefilled_url,
            "event_start_utc": event_start_utc,
            "event_uuid": event_uuid,
            "invitee_uuid": invitee_uuid,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
        if zoom_join_url:
            data["zoom_join_url"] = zoom_join_url
        coll.document(doc_id).set(data)
        logger.info("Stored prefilled link in Firestore doc %s for %s", doc_id, invitee_email)
    except Exception as e:
        logger.warning("Firestore write for prefilled link failed: %s", e)


def _send_prefilled_link_email(
    to_email: str,
    invitee_name: str,
    invitee_email: str,
    prefilled_url: str,
    event_start_utc: str | None,
) -> None:
    """Email the prefilled form link to the host (Kim) via SendGrid. Logs but does not raise on failure."""
    if not SENDGRID_API_KEY or not SENDGRID_FROM_EMAIL or not to_email:
        return
    patient = invitee_name or invitee_email or "Patient"
    event_str = f" at {event_start_utc}" if event_start_utc else ""
    subject = f"Telehealth form link: {patient}{event_str}"
    html = f"""<p>New booking: <strong>{patient}</strong> ({invitee_email}){event_str}</p>
<p><a href="{prefilled_url}">Open prefilled Telehealth Note form</a></p>
<p>Patient email and name are already filled. Add Kim's Note, duration, and Meeting UUID after the call.</p>
<p><small>Link: {prefilled_url}</small></p>"""
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": SENDGRID_FROM_EMAIL, "name": "Telehealth Calendly"},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }
    try:
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if resp.ok:
            logger.info("Sent prefilled form link email to %s for booking %s", to_email, invitee_email)
        else:
            logger.warning("SendGrid failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("SendGrid email failed: %s", e)


def _insert_into_bigquery(rows: list) -> None:
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
    """HTTP handler for Calendly webhooks (invitee.created, invitee.canceled)."""
    if request.method != "POST":
        return ("Method not allowed", 405)
    try:
        payload = request.get_json()
    except Exception:
        return ("Invalid JSON", 400)

    event_type = payload.get("event")
    payload_data = payload.get("payload", {})
    invitee_uri = payload_data.get("uri") or ""
    if isinstance(invitee_uri, dict):
        invitee_uri = invitee_uri.get("uri", "")

    event_uuid, invitee_uuid = _parse_invitee_uri(invitee_uri or "")
    if not event_uuid or not invitee_uuid:
        logger.warning("Could not parse invitee URI from payload")
        return ("OK", 200)

    invitee_data = _fetch_invitee(event_uuid, invitee_uuid, CALENDLY_PAT)
    if not invitee_data:
        return ("OK", 200)

    resource = invitee_data.get("resource", {})
    event_data = resource.get("event", "")
    # BigQuery TIMESTAMP rejects empty string; use None for null
    event_start = resource.get("start_time") or None
    event_end = resource.get("end_time") or None
    # Name and email from API (invitee who just booked); fallback to payload if API omits them
    invitee_email = (resource.get("email") or "").strip() or _str(payload_data.get("email"))
    invitee_name = (resource.get("name") or "").strip() or _str(payload_data.get("name"))
    if not invitee_email and isinstance(payload_data.get("invitee"), dict):
        inv = payload_data["invitee"]
        invitee_email = invitee_email or _str(inv.get("email"))
        invitee_name = invitee_name or _str(inv.get("name"))
    status = resource.get("status", "active")
    canceled = payload_data.get("canceled", False)
    rescheduled = payload_data.get("rescheduled", False)
    host_email = ""
    event_name = ""
    zoom_join_url = ""

    if isinstance(event_data, str) and "scheduled_events" in event_data:
        try:
            ev_resp = requests.get(
                event_data,
                headers={"Authorization": f"Bearer {CALENDLY_PAT}", "Content-Type": "application/json"},
                timeout=10,
            )
            if ev_resp.ok:
                ev_resource = ev_resp.json().get("resource", {})
                event_name = ev_resource.get("name", "")
                if not event_start:
                    event_start = ev_resource.get("start_time") or None
                if not event_end:
                    event_end = ev_resource.get("end_time") or None
                zoom_join_url = _extract_zoom_join_url(ev_resource)
                memberships = ev_resource.get("event_memberships", [])
                if memberships:
                    host_uri = memberships[0].get("user", "")
                    if host_uri:
                        u_resp = requests.get(
                            host_uri,
                            headers={"Authorization": f"Bearer {CALENDLY_PAT}", "Content-Type": "application/json"},
                            timeout=10,
                        )
                        if u_resp.ok:
                            host_email = u_resp.json().get("resource", {}).get("email", "")
        except Exception as e:
            logger.warning("Could not fetch event/host: %s", e)

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
    prefilled_url = _build_prefilled_form_url(invitee_email, invitee_name)
    if prefilled_url:
        row["prefilled_form_url"] = prefilled_url
        logger.info(
            "Prefilled form URL built from Calendly booking: email=%r name=%r (form entry_email=%s entry_name=%s)",
            invitee_email, invitee_name, PREFILL_FORM_ENTRY_EMAIL, PREFILL_FORM_ENTRY_NAME,
        )
    elif PREFILL_FORM_BASE_URL and invitee_email:
        logger.warning("Prefilled URL not built: PREFILL_FORM_ENTRY_EMAIL may be unset or invitee data missing")

    try:
        _insert_into_bigquery([row])
    except Exception as e:
        logger.error("BigQuery insert failed: %s", e)
        return ("Internal error", 500)
    if prefilled_url:
        _store_prefilled_link_firestore(
            event_uuid=event_uuid,
            invitee_uuid=invitee_uuid,
            invitee_email=invitee_email,
            invitee_name=invitee_name,
            prefilled_url=prefilled_url,
            event_start_utc=event_start,
            zoom_join_url=zoom_join_url or "",
        )
        # Email Kim (host) the prefilled link so she can fill notes after the call
        if not canceled:
            to_email = (host_email or "").strip() or HOST_EMAIL
            if to_email:
                _send_prefilled_link_email(
                    to_email=to_email,
                    invitee_name=invitee_name,
                    invitee_email=invitee_email,
                    prefilled_url=prefilled_url,
                    event_start_utc=event_start,
                )
            elif SENDGRID_API_KEY and SENDGRID_FROM_EMAIL:
                logger.warning("Cannot email prefilled link: host_email and HOST_EMAIL both empty")
    return ("OK", 200)
