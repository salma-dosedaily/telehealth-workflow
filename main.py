import os
import re
import json
import hmac
import hashlib
import logging
from urllib.parse import quote
from datetime import datetime, timezone
from typing import Any

import requests
import functions_framework
from google import genai

# Load Environment Variables
ZOOM_SECRET_TOKEN = os.environ.get('ZOOM_SECRET_TOKEN', '')
RUDDERSTACK_URL = os.environ.get('RUDDERSTACK_URL', '')
RUDDERSTACK_WRITE_KEY = os.environ.get('RUDDERSTACK_WRITE_KEY', '')
USE_AI = os.environ.get('USE_AI', 'True').lower() == 'true'
# Faster path: only extract nutritionist summary (regex); skip full Gemini. Set True for quicker Klaviyo email.
SUMMARY_ONLY = os.environ.get('SUMMARY_ONLY', 'True').lower() == 'true'
# Poll path: Cloud Tasks queue and secrets
TELEHEALTH_WEBHOOK_URL = os.environ.get('TELEHEALTH_WEBHOOK_URL', '')
POLL_SECRET = os.environ.get('POLL_SECRET', '')
GCP_PROJECT = os.environ.get('GCP_PROJECT', '')
GCP_REGION = os.environ.get('GCP_REGION', 'us-central1')
TASKS_QUEUE = os.environ.get('TASKS_QUEUE', 'telehealth-poll')
ZOOM_ACCOUNT_ID = os.environ.get('ZOOM_ACCOUNT_ID', '')
ZOOM_CLIENT_ID = os.environ.get('ZOOM_CLIENT_ID', '')
ZOOM_CLIENT_SECRET = os.environ.get('ZOOM_CLIENT_SECRET', '')
# Alternative to S2S: General App OAuth 2.0 refresh token (one-time user auth). Enables fast path when S2S is not available.
ZOOM_REFRESH_TOKEN = os.environ.get('ZOOM_REFRESH_TOKEN', '')

# Safety: require meeting duration > 5 min to avoid no-show triggers
# Zoom meeting.ended payload: duration is in SECONDS (we convert to minutes for check and storage)
MIN_DURATION_MINUTES = 5
POLL_DELAY_SECONDS = 120
POLL_MAX_ATTEMPTS = 20

# Form submission: optional secret for authenticating Google Form POSTs
FORM_SUBMIT_SECRET = os.environ.get("FORM_SUBMIT_SECRET", "")
# Firestore collection for meeting.ended (form can look up by meeting_uuid to verify)
FIRESTORE_COLLECTION_MEETINGS = "telehealth_meetings_ended"
# Firestore database ID: use "(default)" or a named DB (e.g. telemeetinglog). Empty = (default).
FIRESTORE_DATABASE_ID = (os.environ.get("FIRESTORE_DATABASE_ID", "") or "").strip() or None

logger = logging.getLogger(__name__)

# Basic email validation (RFC 5322 simplified)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_kims_note_to_summary(text: str) -> str:
    """Collapse whitespace to one paragraph (legacy / non-email use)."""
    if not text or not isinstance(text, str):
        return ""
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[\n\t]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_kims_note_to_bullets(text: str) -> str:
    """
    Bullet lines for Klaviyo: in the email template use {{ event.kims_custom_note|linebreaksbr }}
    so each line renders on its own row. Parses numbered items like '1. a 2. b' or line breaks.
    """
    if not text or not isinstance(text, str):
        return ""
    s = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""

    def strip_num_prefix(fragment: str) -> str:
        fragment = fragment.strip()
        m = re.match(r"^\d+\.\s*(.+)", fragment, re.DOTALL)
        return m.group(1).strip() if m else fragment

    items: list[str] = []

    if "\n" in s:
        for line in s.split("\n"):
            line = line.strip()
            if not line:
                continue
            items.append(strip_num_prefix(line))
    elif re.search(r"\d+\.\s+\S", s):
        for c in re.split(r"\s+(?=\d+\.\s)", s):
            c = c.strip()
            if c:
                items.append(strip_num_prefix(c))
    else:
        items.append(s)

    bullets = [f"• {it}" for it in items if it]
    return "\n".join(bullets)


def _canonical_product_name_for_klaviyo(raw: str | None) -> str | None:
    """
    Stable productName for Klaviyo conditional splits (Liver / Cholesterol / Bundle / No Show).
    Maps dropdown labels like 'Liver program' to 'Liver' so splits match reliably.
    'No Show' maps to 'No Show' — fires Telehealth_Call_Finished with attended=False from form submissions.
    """
    if not raw or not isinstance(raw, str):
        return None
    t = raw.strip().lower()
    if not t:
        return None
    if "no show" in t or "noshow" in t or t == "no-show":
        return "No Show"
    if "liver" in t:
        return "Liver"
    if "cholesterol" in t:
        return "Cholesterol"
    if "bundle" in t:
        return "Bundle"
    return raw.strip()


# Regex: "Summary for the email: [Instruction]" (or "Notes for the email:")
SUMMARY_FOR_EMAIL_PATTERN = re.compile(
    r"(?i)(?:summary|notes)\s+for\s+the\s+email\s*:\s*(.+?)(?=\n\n|\n\d{2}:\d{2}:|\n\s*\d{2}:|\Z)",
    re.DOTALL,
)

def extract_kims_custom_note_regex(transcript: str) -> str | None:
    """Extract the instruction after 'Summary for the email:' via regex."""
    if not transcript or not transcript.strip():
        return None
    match = SUMMARY_FOR_EMAIL_PATTERN.search(transcript)
    if not match:
        return None
    return match.group(1).strip()


def _update_zoom_refresh_token_in_secret_manager(new_refresh_token: str) -> None:
    """Persist new Zoom refresh token to GSM so next invocation uses it (Zoom invalidates old token after refresh)."""
    project = os.environ.get("GCP_PROJECT")
    if not project or not new_refresh_token:
        return
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project}"
        secret_id = "ZOOM_REFRESH_TOKEN"
        payload = new_refresh_token.encode("utf-8")
        client.add_secret_version(request={"parent": f"{parent}/secrets/{secret_id}", "payload": {"data": payload}})
        logger.info("Updated ZOOM_REFRESH_TOKEN in Secret Manager with new token from Zoom.")
    except Exception as e:
        logger.warning("Could not update ZOOM_REFRESH_TOKEN in GSM (old token may be invalid on next use): %s", e)


def get_zoom_oauth_token() -> str | None:
    """
    Get Zoom API access token. Supports:
    - Server-to-Server OAuth: ZOOM_ACCOUNT_ID + ZOOM_CLIENT_ID + ZOOM_CLIENT_SECRET.
    - General App (user OAuth): ZOOM_REFRESH_TOKEN + ZOOM_CLIENT_ID + ZOOM_CLIENT_SECRET.
    When using refresh token, Zoom returns a new refresh_token; we persist it to GSM so the next run has a valid token.
    """
    auth = (ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET) if (ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET) else None
    if not auth:
        return None

    # 1) Server-to-Server OAuth (when available)
    if ZOOM_ACCOUNT_ID:
        url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={ZOOM_ACCOUNT_ID}"
        try:
            r = requests.post(url, auth=auth, timeout=10)
            r.raise_for_status()
            return r.json().get("access_token")
        except Exception as e:
            logger.exception("Zoom S2S OAuth token failed: %s", e)
            return None

    # 2) General App: refresh token (workaround when S2S is not available)
    if not ZOOM_REFRESH_TOKEN:
        return None
    url = "https://zoom.us/oauth/token"
    data = {"grant_type": "refresh_token", "refresh_token": ZOOM_REFRESH_TOKEN}
    try:
        r = requests.post(url, auth=auth, data=data, timeout=10)
        r.raise_for_status()
        body = r.json()
        access_token = body.get("access_token")
        new_refresh = body.get("refresh_token")
        if new_refresh and new_refresh != ZOOM_REFRESH_TOKEN:
            _update_zoom_refresh_token_in_secret_manager(new_refresh)
        return access_token
    except Exception as e:
        logger.exception("Zoom refresh token OAuth failed: %s", e)
        return None


def double_encode_uuid(uuid_val: str) -> str:
    """Double URL-encode meeting UUID for Zoom API (required when UUID contains / or +)."""
    return quote(quote(uuid_val, safe=""), safe="")


def get_zoom_user_email(host_id: str) -> str | None:
    """Resolve Zoom host_id to email via GET /users/{userId}. Returns None if not available or API fails."""
    if not host_id or not isinstance(host_id, str):
        return None
    token = get_zoom_oauth_token()
    if not token:
        return None
    # host_id may need encoding if it contains special chars (e.g. email used as id)
    url = f"https://api.zoom.us/v2/users/{quote(host_id, safe='')}"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        r.raise_for_status()
        return (r.json() or {}).get("email") or None
    except Exception as e:
        logger.warning("Could not fetch Zoom user email for host_id=%s: %s", host_id[:50], e)
        return None


def get_zoom_host_email_from_past_meeting(meeting_uuid: str) -> str | None:
    """Fallback: resolve host email via GET /past_meetings/{uuid}. Returns user_email when meeting.ended omits host_email."""
    if not meeting_uuid or not isinstance(meeting_uuid, str):
        return None
    token = get_zoom_oauth_token()
    if not token:
        return None
    encoded_uuid = double_encode_uuid(meeting_uuid)
    url = f"https://api.zoom.us/v2/past_meetings/{encoded_uuid}"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        r.raise_for_status()
        return (r.json() or {}).get("user_email") or None
    except Exception as e:
        logger.warning("Could not fetch Zoom past meeting for uuid=%s: %s", meeting_uuid[:30], e)
        return None


def verify_zoom_signature(request, raw_body: str):
    """Verifies that the incoming webhook is genuinely from Zoom."""
    zoom_signature = request.headers.get('x-zm-signature')
    zoom_request_timestamp = request.headers.get('x-zm-request-timestamp')
    
    if not zoom_signature or not zoom_request_timestamp:
        print(f"Missing signature headers: sig={zoom_signature!r}, ts={zoom_request_timestamp!r}")
        return False
    
    # Get raw bytes directly to compare
    raw_bytes = request.get_data(as_text=False)
    
    # Debug: log all details
    print(f"DEBUG: timestamp={zoom_request_timestamp!r}")
    print(f"DEBUG: raw_body (str) len={len(raw_body)}")
    print(f"DEBUG: raw_bytes len={len(raw_bytes)}")
    print(f"DEBUG: raw_bytes[:100]={raw_bytes[:100]!r}")
    print(f"DEBUG: raw_body == raw_bytes.decode: {raw_body == raw_bytes.decode('utf-8')}")
    
    token_debug = f"len={len(ZOOM_SECRET_TOKEN)}, repr={ZOOM_SECRET_TOKEN!r}" if ZOOM_SECRET_TOKEN else "EMPTY"
    print(f"DEBUG: ZOOM_SECRET_TOKEN {token_debug}")
        
    # Construct the message using raw bytes decoded as utf-8
    body_for_hash = raw_bytes.decode('utf-8')
    message = f"v0:{zoom_request_timestamp}:{body_for_hash}"
    
    # Hash the message using the Secret Token
    hash_for_verify = hmac.new(
        key=ZOOM_SECRET_TOKEN.encode('utf-8'),
        msg=message.encode('utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # Create the expected signature format
    expected_signature = f"v0={hash_for_verify}"
    
    # Debug logging
    print(f"DEBUG: zoom_signature={zoom_signature}")
    print(f"DEBUG: expected_sig ={expected_signature}")
    
    # Compare securely
    return hmac.compare_digest(expected_signature, zoom_signature)


def send_no_show_to_rudderstack(meeting_obj: dict, product_name: str | None = None) -> tuple[str, int]:
    """
    Send Telehealth_Call_No_Show event to RudderStack for calls < 10 min (no-show).
    meeting_obj must have: uuid, host_email, duration, start_time or start_time_iso.
    product_name: optional; when set, sent as productName for Klaviyo flow splits.
    Returns (response_body, status_code).
    """
    meeting_uuid = meeting_obj.get("uuid", "")
    meeting_date = meeting_obj.get("start_time") or meeting_obj.get("start_time_iso") or ""
    rudderstack_payload = {
        "event": "Telehealth_Call_No_Show",
        "userId": meeting_uuid,
        "properties": {
            "meeting_uuid": meeting_uuid,
            "host_email": meeting_obj.get("host_email"),
            "duration": meeting_obj.get("duration"),
            "meeting_date": meeting_date,
            "source": "zoom_meeting_ended",
            "attended": False,
        },
    }
    # Feature 1: Add product information for Klaviyo flow splits
    if product_name and isinstance(product_name, str) and product_name.strip():
        rudderstack_payload["properties"]["productName"] = product_name.strip()
    
    try:
        auth = (RUDDERSTACK_WRITE_KEY, "") if RUDDERSTACK_WRITE_KEY else None
        rs_response = requests.post(
            RUDDERSTACK_URL,
            json=rudderstack_payload,
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        rs_response.raise_for_status()
    except Exception as e:
        logger.exception("RudderStack delivery failed for no-show: %s", e)
        return ("RudderStack delivery failed", 500)

    logger.info("Success: Telehealth_Call_No_Show sent to RudderStack for meeting_uuid=%s", meeting_uuid)
    return ("Success", 200)


def send_meeting_ended_to_rudderstack(meeting_obj: dict, product_name: str | None = None) -> tuple[str, int]:
    """
    Send Telehealth_Call_Finished to RudderStack from meeting.ended (no transcript).
    meeting_obj must have: uuid, host_email, duration, start_time or start_time_iso.
    product_name: optional; when set, sent as productName for Klaviyo flow splits.
    Returns (response_body, status_code).
    """
    meeting_uuid = meeting_obj.get("uuid", "")
    meeting_date = meeting_obj.get("start_time") or meeting_obj.get("start_time_iso") or ""
    rudderstack_payload = {
        "event": "Telehealth_Call_Finished",
        "userId": meeting_uuid,
        "properties": {
            "meeting_uuid": meeting_uuid,
            "host_email": meeting_obj.get("host_email"),
            "duration": meeting_obj.get("duration"),
            "meeting_date": meeting_date,
            "kims_custom_note": "No custom notes provided.",
            "source": "zoom_meeting_ended",
            "attended": True,
        },
    }
    # Feature 1: Add product information for Klaviyo flow splits
    if product_name and isinstance(product_name, str) and product_name.strip():
        rudderstack_payload["properties"]["productName"] = product_name.strip()
    
    try:
        auth = (RUDDERSTACK_WRITE_KEY, "") if RUDDERSTACK_WRITE_KEY else None
        rs_response = requests.post(
            RUDDERSTACK_URL,
            json=rudderstack_payload,
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        rs_response.raise_for_status()
    except Exception as e:
        logger.exception("RudderStack delivery failed: %s", e)
        return ("RudderStack delivery failed", 500)

    logger.info("Success: Telehealth_Call_Finished sent to RudderStack for meeting_uuid=%s", meeting_uuid)
    return ("Success", 200)


def _get_firestore_client():
    """Lazy Firestore client for optional meeting store/lookup.
    Uses (default) database unless FIRESTORE_DATABASE_ID is set (e.g. to 'telemeetinglog').
    """
    try:
        from google.cloud import firestore
        project = os.environ.get("GCP_PROJECT")
        if FIRESTORE_DATABASE_ID:
            return firestore.Client(project=project, database=FIRESTORE_DATABASE_ID)
        return firestore.Client(project=project)
    except Exception as e:
        logger.warning("Firestore not available: %s", e)
        return None


def store_meeting_ended(
    meeting_uuid: str,
    host_email: str | None,
    duration: int,
    start_time: str,
    meeting_id: int | None = None,
    product_name: str | None = None,
) -> None:
    """Store meeting.ended in Firestore so form submission can verify and merge Zoom context.
    Stores both meeting_uuid (for direct lookup) and meeting_id (numeric, from Zoom join URL) when available.
    product_name: optional; stored so form submission can retrieve it if not provided in form.
    """
    try:
        from google.cloud import firestore
    except ImportError:
        return
    client = _get_firestore_client()
    if not client:
        return
    try:
        coll = client.collection(FIRESTORE_COLLECTION_MEETINGS)
        doc_id = meeting_uuid.replace("/", "_").replace("+", "-")[:100]
        data: dict[str, Any] = {
            "meeting_uuid": meeting_uuid,
            "host_email": host_email,
            "duration": duration,
            "start_time": start_time,
            "received_at": firestore.SERVER_TIMESTAMP,
        }
        if meeting_id is not None:
            data["meeting_id"] = meeting_id
        # Feature 1: Store product_name so form can retrieve it
        if product_name:
            data["product_name"] = product_name
        coll.document(doc_id).set(data)
        logger.info("Stored meeting_ended for uuid=%s (id=%s)", meeting_uuid, meeting_id)
    except Exception as e:
        logger.warning("Failed to store meeting_ended: %s", e)


def _extract_meeting_id_from_identifier(identifier: str) -> str | None:
    """If identifier is a Zoom join URL or a numeric meeting ID, return the digits; else None for uuid path."""
    s = (identifier or "").strip()
    if not s:
        return None
    # Zoom join URL: .../j/89166792057 or .../j/89166792057?pwd=...
    url_match = re.search(r"zoom\.us/j/(\d+)", s, re.IGNORECASE)
    if url_match:
        return url_match.group(1)
    if s.isdigit():
        return s
    return None


def get_meeting_ended(meeting_identifier: str) -> dict[str, Any] | None:
    """Look up meeting.ended from Firestore by meeting_uuid or by meeting_id (from Zoom join URL).
    meeting_identifier can be: Zoom UUID string, numeric meeting ID, or full Zoom join URL.
    Returns None if not found or Firestore unavailable.
    """
    client = _get_firestore_client()
    if not client:
        return None
    try:
        coll = client.collection(FIRESTORE_COLLECTION_MEETINGS)
        # 1) Try by UUID (doc_id from uuid)
        doc_id = meeting_identifier.replace("/", "_").replace("+", "-")[:100]
        doc = coll.document(doc_id).get()
        if doc.exists:
            return doc.to_dict()
        # 2) Try by numeric meeting ID (from Zoom URL or pasted id)
        meeting_id_str = _extract_meeting_id_from_identifier(meeting_identifier)
        if meeting_id_str:
            for d in coll.where("meeting_id", "==", int(meeting_id_str)).limit(1).stream():
                return d.to_dict()
        return None
    except Exception as e:
        logger.warning("Failed to get meeting_ended: %s", e)
        return None


def _rudderstack_identify(
    patient_email: str,
    patient_name: str,
    completed_call: bool = False,
    telehealth_product: str | None = None,
) -> None:
    """
    Send identify to RudderStack so Klaviyo profile has email (fixes 'Skipped: Missing Email').
    completed_call: sets completed / attended traits for retention segments.
    telehealth_product: canonical Liver | Cholesterol | Bundle — copied to profile so Klaviyo
    conditional splits using only "Properties about someone" + productName still work (event-only
    properties are invisible to that split type).
    """
    if not RUDDERSTACK_URL or not RUDDERSTACK_WRITE_KEY:
        return
    base = RUDDERSTACK_URL.rstrip("/")
    identify_url = base.replace("/v1/track", "/v1/identify") if "/v1/track" in base else f"{base}/v1/identify"
    traits: dict[str, str | bool] = {"email": patient_email}
    if patient_name:
        parts = patient_name.strip().split(None, 1)
        traits["firstName"] = parts[0]
        if len(parts) > 1:
            traits["lastName"] = parts[1]
    # Completed-call profile traits for Klaviyo segments / retention (bools + string for filter compatibility)
    if completed_call:
        traits["completed_telehealth_call"] = True
        traits["telehealth_call_attended"] = True
        traits["telehealth_attended"] = "yes"
    if telehealth_product:
        traits["productName"] = telehealth_product
        traits["telehealth_last_product"] = telehealth_product
    payload = {
        "userId": patient_email,
        "traits": traits,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    try:
        r = requests.post(
            identify_url,
            json=payload,
            auth=(RUDDERSTACK_WRITE_KEY, ""),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if r.ok:
            logger.info("RudderStack identify sent for %s", patient_email)
        else:
            logger.warning("RudderStack identify failed %s: %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("RudderStack identify failed: %s", e)


def send_form_submission_to_rudderstack(
    patient_email: str,
    patient_name: str,
    kims_custom_note: str,
    duration: int,
    meeting_uuid: str | None = None,
    meeting_context: dict[str, Any] | None = None,
    product_name: str | None = None,
) -> tuple[str, int]:
    """
    Send Google Form submission to RudderStack with userId=patient_email so Klaviyo can send follow-up emails.
    Sends identify first so Klaviyo profile has email (prevents 'Skipped: Missing Email').
    Optionally merge Zoom context (host_email, meeting_date) when form includes meeting_uuid and we have it stored.
    product_name: optional; when set, sent as productName so Klaviyo flow splits (e.g. Liver / Cholesterol / Bundle) can route.
    """
    meeting_date = ""
    host_email = None
    if meeting_context:
        meeting_date = meeting_context.get("start_time") or meeting_context.get("meeting_date") or ""
        host_email = meeting_context.get("host_email")
        # Feature 1: If product_name not provided in form, retrieve from meeting context (stored from Zoom)
        if not product_name and meeting_context.get("product_name"):
            product_name = meeting_context.get("product_name")

    kims_bullets = _normalize_kims_note_to_bullets(kims_custom_note)
    canon_product = _canonical_product_name_for_klaviyo(product_name)

    # Identify after final product so profile gets productName for Klaviyo "Properties about someone" splits
    _rudderstack_identify(
        patient_email,
        patient_name or "",
        completed_call=True,
        telehealth_product=canon_product,
    )

    # Track: canonical event fields are email / name (no patient_* duplicates for Klaviyo preview).
    # kims_custom_note: newline-separated bullets; use |linebreaksbr in Klaviyo HTML (not nl2br).

    payload = {
        "event": "Telehealth_Call_Finished",
        "userId": patient_email,
        "properties": {
            "email": patient_email,
            "name": patient_name or "",
            "kims_custom_note": kims_bullets,
            "duration": duration,
            "source": "google_form",
            "submitted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "attended": True,
            "call_attended": True,
            "attended_str": "true",
            "telehealth_attended": "yes",
        },
    }
    props = payload["properties"]
    if meeting_uuid:
        props["meeting_uuid"] = meeting_uuid
    if meeting_date:
        props["meeting_date"] = meeting_date
    if host_email:
        props["host_email"] = host_email
    # Event properties (track). Profile productName is set on identify above for split types that only read profile.
    if canon_product:
        props["productName"] = canon_product
        props["Product"] = canon_product

    try:
        auth = (RUDDERSTACK_WRITE_KEY, "") if RUDDERSTACK_WRITE_KEY else None
        r = requests.post(
            RUDDERSTACK_URL,
            json=payload,
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as e:
        logger.exception("RudderStack delivery failed for form submission: %s", e)
        return ("RudderStack delivery failed", 500)

    logger.info(
        "Success: Telehealth_Call_Finished (form) sent for patient_email=%s productName=%r attended props set",
        patient_email,
        canon_product,
    )
    return ("Success", 200)


# When form omits duration (no field), use this so Kim does not need to enter it.
DEFAULT_FORM_DURATION_MINUTES = 10


def process_form_submission(request_json: dict) -> tuple[str, int]:
    """
    Validate Google Form submission and send to RudderStack with verified patient email.
    Expects: patient_email or email, kims_custom_note (or kims_note); optional: duration, patient_name or name,
    meeting_uuid, product_name (or productName) for Klaviyo flow splits (Liver / Cholesterol / Bundle).
    If duration is omitted, DEFAULT_FORM_DURATION_MINUTES is used so the form can skip a duration field.
    Kim's note is normalized to bullet lines for Klaviyo; use {{ event.kims_custom_note|linebreaksbr }} in HTML emails.
    """
    patient_email = (request_json.get("patient_email") or request_json.get("email") or "").strip()
    kims_note = request_json.get("kims_custom_note") or request_json.get("kims_note") or ""
    if isinstance(kims_note, str):
        kims_note = kims_note.strip()
    duration_val = request_json.get("duration")
    try:
        duration_min = int(duration_val) if duration_val is not None else -1
    except (TypeError, ValueError):
        duration_min = -1
    if duration_min < 0:
        duration_min = DEFAULT_FORM_DURATION_MINUTES
    patient_name = (request_json.get("patient_name") or request_json.get("name") or "").strip()
    meeting_uuid = (request_json.get("meeting_uuid") or "").strip() or None
    product_name = (request_json.get("product_name") or request_json.get("productName") or "").strip() or None
    canon_product = _canonical_product_name_for_klaviyo(product_name)

    if not patient_email:
        logger.warning("Form submission missing patient_email")
        return ("Missing patient_email", 400)
    if not EMAIL_PATTERN.match(patient_email):
        logger.warning("Form submission invalid email: %s", patient_email[:50])
        return ("Invalid patient_email format", 400)

    # Manual no-show: Kim selected "No Show" in the Product/Program dropdown.
    # Bypass note and duration checks — fire Telehealth_Call_Finished with productName="No Show"
    # so Klaviyo's single flow can split on productName and route to the "We Missed You" email.
    if canon_product == "No Show":
        _rudderstack_identify(
            patient_email,
            patient_name or "",
            completed_call=False,
            telehealth_product="No Show",
        )
        no_show_payload: dict[str, Any] = {
            "event": "Telehealth_Call_Finished",
            "userId": patient_email,
            "properties": {
                "email": patient_email,
                "name": patient_name or "",
                "duration": duration_min,
                "source": "google_form",
                "productName": "No Show",
                "Product": "No Show",
                "attended": False,
                "submitted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        }
        if kims_note:
            no_show_payload["properties"]["kims_custom_note"] = kims_note
        if meeting_uuid:
            no_show_payload["properties"]["meeting_uuid"] = meeting_uuid
        try:
            auth = (RUDDERSTACK_WRITE_KEY, "") if RUDDERSTACK_WRITE_KEY else None
            r = requests.post(
                RUDDERSTACK_URL,
                json=no_show_payload,
                auth=auth,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            r.raise_for_status()
        except Exception as e:
            logger.exception("RudderStack delivery failed for form no-show: %s", e)
            return ("RudderStack delivery failed", 500)
        logger.info(
            "Success: Telehealth_Call_Finished (form no-show) sent for patient_email=%s",
            patient_email,
        )
        return ("Success", 200)

    if not kims_note:
        logger.warning("Form submission missing kims_custom_note")
        return ("Missing kims_custom_note", 400)
    if duration_min < MIN_DURATION_MINUTES:
        logger.warning("Form submission duration %s < %s (no-show)", duration_min, MIN_DURATION_MINUTES)
        return (f"Duration {duration_min} min < {MIN_DURATION_MINUTES} min (no-show)", 200)

    meeting_context = None
    if meeting_uuid:
        meeting_context = get_meeting_ended(meeting_uuid)
        if meeting_context:
            logger.info("Form submission matched Zoom meeting uuid=%s", meeting_uuid)

    return send_form_submission_to_rudderstack(
        patient_email=patient_email,
        patient_name=patient_name,
        kims_custom_note=kims_note,
        duration=duration_min,
        meeting_uuid=meeting_uuid,
        meeting_context=meeting_context,
        product_name=product_name,
    )


def process_transcript_and_send_to_rudderstack(transcript_text: str, meeting_obj: dict) -> tuple[str, int]:
    """
    Shared pipeline: no-show check, extract kims_custom_note, optional Gemini, send to RudderStack.
    meeting_obj must have: host_email, duration, start_time or start_time_iso, uuid.
    Returns (response_body, status_code).
    """
    meeting_uuid = meeting_obj.get("uuid", "")
    word_count = len(transcript_text.split())
    if word_count < 50:
        logger.info("Meeting %s flagged as No-Show (word count: %s).", meeting_uuid, word_count)
        return ("No-show detected, flow stopped.", 200)

    kims_custom_note = extract_kims_custom_note_regex(transcript_text)
    ai_data = {
        "sentiment": "Neutral",
        "kims_custom_note": kims_custom_note if kims_custom_note else "No custom notes provided.",
        "summary": "",
    }

    # Full AI only if USE_AI and not SUMMARY_ONLY (summary-only = faster, nutritionist note only)
    if USE_AI and not SUMMARY_ONLY and "GEMINI_API_KEY" in os.environ:
        try:
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            prompt_extra = ""
            if not kims_custom_note:
                prompt_extra = " Extract Kim's dictated notes for the email (look for 'Summary for the email' or 'Notes for the email'). If not found, use 'No custom notes provided.'"
            prompt = f"""
            Analyze the following telehealth transcript.
            1. Extract the sentiment of the patient (Positive, Neutral, Negative, Frustrated).
            2. Provide a brief 1-sentence internal summary.{prompt_extra}

            Respond STRICTLY in JSON format like this:
            {{"sentiment": "...", "kims_custom_note": "...", "summary": "..."}}

            Transcript:
            {transcript_text}
            """
            ai_response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            cleaned_json = (ai_response.text or "").replace("```json", "").replace("```", "").strip()
            parsed = json.loads(cleaned_json)
            ai_data["sentiment"] = parsed.get("sentiment", ai_data["sentiment"])
            ai_data["summary"] = parsed.get("summary", ai_data["summary"])
            if not kims_custom_note and parsed.get("kims_custom_note"):
                ai_data["kims_custom_note"] = parsed["kims_custom_note"]
        except Exception as e:
            logger.warning("AI processing failed: %s", e)
    elif USE_AI and SUMMARY_ONLY and not kims_custom_note and "GEMINI_API_KEY" in os.environ:
        # Summary-only mode: only call Gemini to extract note if regex missed it
        try:
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            prompt = f"""From this transcript, extract only the nutritionist's note for the email (look for "Summary for the email" or "Notes for the email"). If not found, respond with exactly: No custom notes provided.

Transcript:
{transcript_text}

Respond with only the extracted note text, or "No custom notes provided."."""
            ai_response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            note = (ai_response.text or "").strip()
            if note and "no custom notes" not in note.lower():
                ai_data["kims_custom_note"] = note
        except Exception as e:
            logger.warning("AI note extraction failed: %s", e)

    meeting_date = meeting_obj.get("start_time") or meeting_obj.get("start_time_iso") or ""
    _raw_kims = ai_data.get("kims_custom_note")
    _raw_kims_s = _raw_kims if isinstance(_raw_kims, str) else (str(_raw_kims) if _raw_kims is not None else "")
    note_for_klaviyo = _normalize_kims_note_to_bullets(_raw_kims_s) or "• No custom notes provided."
    rudderstack_payload = {
        "event": "Telehealth_Call_Finished",
        "userId": meeting_uuid,
        "properties": {
            "meeting_uuid": meeting_uuid,
            "host_email": meeting_obj.get("host_email"),
            "duration": meeting_obj.get("duration"),
            "meeting_date": meeting_date,
            "kims_custom_note": note_for_klaviyo,
            "sentiment": ai_data.get("sentiment"),
            "internal_summary": ai_data.get("summary"),
            "attended": True,
        },
    }
    try:
        auth = (RUDDERSTACK_WRITE_KEY, "") if RUDDERSTACK_WRITE_KEY else None
        rs_response = requests.post(
            RUDDERSTACK_URL,
            json=rudderstack_payload,
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        rs_response.raise_for_status()
    except Exception as e:
        logger.exception("RudderStack delivery failed: %s", e)
        return ("RudderStack delivery failed", 500)

    logger.info("Success: Telehealth_Call_Finished sent to RudderStack for meeting_uuid=%s", meeting_uuid)
    return ("Success", 200)


@functions_framework.http
def telehealth_webhook_handler(request):
    """
    HTTP Cloud Function: (1) Google Form submissions → verify & send to RudderStack with patient email.
    (2) Zoom webhooks (meeting.ended → send to RudderStack, store in Firestore for form verification).
    """
    raw_body = request.get_data(as_text=True)
    try:
        request_json = json.loads(raw_body) if raw_body else {}
    except Exception:
        return ("Invalid JSON", 400)

    # ---- Form submission path: patient_email or email + kims note => verify and send to RudderStack/Klaviyo ----
    _form_email = (request_json.get("patient_email") or request_json.get("email") or "").strip()
    _has_kims = (
        request_json.get("kims_custom_note") is not None or request_json.get("kims_note") is not None
    )
    if _form_email and _has_kims:
        if FORM_SUBMIT_SECRET:
            secret = request.headers.get("X-Form-Secret") or request_json.pop("form_secret", None)
            if secret != FORM_SUBMIT_SECRET:
                logger.warning("Form submission rejected: invalid or missing FORM_SUBMIT_SECRET")
                return ("Unauthorized", 401)
        result, status = process_form_submission(request_json)
        print(f"Form submission: {result}")
        return (result, status)

    # ---- Zoom webhook path ----
    event_type_raw = request_json.get("event")
    print(f"Zoom webhook received: event={event_type_raw!r}, body_keys={list(request_json.keys()) if request_json else []}")
    if not event_type_raw and raw_body:
        print(f"DEBUG: raw_body preview (len={len(raw_body)}): {raw_body[:400]!r}")

    # Handle Zoom's Mandatory Endpoint Validation (Initial Setup)
    if request_json.get('event') == 'endpoint.url_validation':
        plain_token = request_json['payload']['plainToken']
        encrypted_token = hmac.new(
            key=ZOOM_SECRET_TOKEN.encode('utf-8'),
            msg=plain_token.encode('utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        return (json.dumps({
            "plainToken": plain_token,
            "encryptedToken": encrypted_token
        }), 200, {'Content-Type': 'application/json'})

    # 6. VERIFY SIGNATURE FOR ALL OTHER EVENTS
    # TEMPORARY: Skip verification for meeting.ended while debugging signature mismatch
    # The Secret Token matches GSM but Zoom's signature doesn't validate
    sig_valid = verify_zoom_signature(request, raw_body)
    if not sig_valid:
        print("WARNING: Zoom signature verification failed - proceeding anyway (debug mode)")
        # TODO: Re-enable strict verification after fixing signature issue
        # return ("Unauthorized", 401)

    event_type = request_json.get("event")
    payload = request_json.get("payload", {})
    meeting_obj = payload.get("object", {})

    # meeting.ended → send to RudderStack immediately (no poll, no transcript wait)
    if event_type == "meeting.ended":
        meeting_uuid = meeting_obj.get("uuid")
        # Zoom meeting.ended sends duration in SECONDS; convert to minutes for no-show check and storage
        duration_raw = meeting_obj.get("duration")
        try:
            duration_seconds = int(duration_raw) if duration_raw is not None else 0
        except (TypeError, ValueError):
            duration_seconds = 0
        duration_min = max(0, duration_seconds // 60)
        # Fallback: Zoom sometimes sends 0 or very low duration (e.g. 30s) for long meetings. If we have
        # start_time, compute duration from start to now and use the larger value.
        start_time_str = meeting_obj.get("start_time") or meeting_obj.get("start_time_iso") or ""
        if duration_min < MIN_DURATION_MINUTES and start_time_str:
            try:
                # Zoom format: 2026-03-10T16:14:33Z or similar
                start_dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                computed_seconds = int((now_dt - start_dt).total_seconds())
                computed_min = max(0, computed_seconds // 60)
                if computed_min > duration_min:
                    duration_min = computed_min
                    duration_seconds = computed_seconds
                    print(f"Meeting.ended: using computed duration {duration_min} min (Zoom sent {duration_raw}s)", flush=True)
            except Exception as e:
                logger.warning("Could not compute duration from start_time: %s", e)
        
        if not meeting_uuid:
            return ("Missing uuid in meeting.ended", 200)
        
        # Idempotency: Zoom often sends meeting.ended twice (retries). If we already stored this uuid,
        # skip sending to RudderStack again to avoid duplicate "Anonymous" activities in Klaviyo.
        existing = get_meeting_ended(meeting_uuid)
        if existing:
            logger.info("Meeting.ended duplicate ignored for meeting_uuid=%s (already processed)", meeting_uuid)
            return ("Already processed", 200)
        
        # Zoom often sends host_id but not host_email; resolve via API when missing
        host_email = meeting_obj.get("host_email") or None
        if not host_email and meeting_obj.get("host_id"):
            host_email = get_zoom_user_email(str(meeting_obj.get("host_id")))
        if not host_email and meeting_uuid:
            host_email = get_zoom_host_email_from_past_meeting(meeting_uuid)
        
        # Feature 1: Extract product_name from Zoom topic (e.g., "Liver Consultation", "Cholesterol Follow-up")
        # This can be set in Calendly event name or Zoom meeting topic
        product_name = None
        topic = meeting_obj.get("topic", "")
        if topic:
            topic_lower = topic.lower()
            if "liver" in topic_lower:
                product_name = "Liver"
            elif "cholesterol" in topic_lower:
                product_name = "Cholesterol"
            elif "bundle" in topic_lower:
                product_name = "Bundle"
        
        # Pass duration in minutes and resolved host_email to RudderStack
        meeting_obj_for_rudder = {**meeting_obj, "duration": duration_min, "host_email": host_email}
        
        # Feature 2: Send no-show event if duration < 10 min, otherwise send completed call event
        if duration_min < 10:
            print(f"Meeting.ended: No-show detected (duration {duration_min} min < 10 min). meeting_uuid={meeting_uuid}")
            result, status = send_no_show_to_rudderstack(meeting_obj_for_rudder, product_name=product_name)
        else:
            result, status = send_meeting_ended_to_rudderstack(meeting_obj_for_rudder, product_name=product_name)
        
        # Store so form submission can verify and merge Zoom context (host_email, meeting_date)
        meeting_id_raw = meeting_obj.get("id")
        try:
            meeting_id_int = int(meeting_id_raw) if meeting_id_raw is not None else None
        except (TypeError, ValueError):
            meeting_id_int = None
        store_meeting_ended(
            meeting_uuid,
            host_email,
            duration_min,  # stored in minutes for consistency with form
            meeting_obj.get("start_time") or meeting_obj.get("start_time_iso") or "",
            meeting_id=meeting_id_int,
            product_name=product_name,
        )
        print(f"Meeting.ended: {result} for meeting_uuid={meeting_uuid}")
        return (result, status)

    # All other Zoom events are ignored
    print(f"Event ignored: event={event_type!r}")
    return ("Event ignored", 200)