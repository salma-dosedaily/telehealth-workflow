"""
Zoom OAuth 2.0 callback (HTTPS). Use when Zoom requires a secure redirect URL.
Deploy once; add the callback URL to your Zoom General App; visit / to start auth.
"""
import os
import html as html_stdlib
import logging
import urllib.parse
import requests
import functions_framework

ZOOM_CLIENT_ID = os.environ.get("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.environ.get("ZOOM_CLIENT_SECRET", "")
GCP_PROJECT = os.environ.get("GCP_PROJECT", "")

logger = logging.getLogger(__name__)


def _redirect_uri(request) -> str:
    """Return redirect URI without /callback - matches Zoom's expected format."""
    return "https://zoom-oauth-callback-pshv76iija-uc.a.run.app"


def _path_and_method(request):
    """Safely get path and method (Cloud Run/Gen2 request shape may vary)."""
    path = (getattr(request, "path", None) or "").strip("/") or ""
    method = (getattr(request, "method", None) or "GET").upper()
    return path, method


def _has_code(request) -> bool:
    """Check if request has OAuth code parameter."""
    args = getattr(request, "args", None) or {}
    return bool(args.get("code") if hasattr(args, "get") else None)


@functions_framework.http
def zoom_oauth_callback(request):
    try:
        path, method = _path_and_method(request)
        # Handle callback at root when code is present (Zoom's redirect)
        if method == "GET" and path == "" and _has_code(request):
            return _handle_callback(request)
        # Serve authorize page at root when no code
        if method == "GET" and path == "":
            return _serve_authorize_page(request)
        # Also handle /callback path for backwards compatibility
        if method == "GET" and path == "callback":
            return _handle_callback(request)
        return ("Not Found", 404)
    except Exception as e:
        logger.exception("zoom_oauth_callback error: %s", e)
        return (f"Internal error: {e}", 500)


def _serve_authorize_page(request):
    """Serve a page with a link to Zoom authorize (HTTPS redirect_uri)."""
    if not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
        html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Zoom OAuth – Config needed</title></head>
<body>
  <h2>Zoom credentials not set</h2>
  <p>Set ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET on this Cloud Function and redeploy.</p>
  <p>Example: <code>gcloud functions deploy zoom_oauth_callback ... --update-env-vars=ZOOM_CLIENT_ID=xxx,ZOOM_CLIENT_SECRET=xxx</code></p>
</body></html>"""
        return (html, 200, {"Content-Type": "text/html; charset=utf-8"})
    redirect_uri = _redirect_uri(request)
    auth_url = (
        "https://zoom.us/oauth/authorize?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": ZOOM_CLIENT_ID,
            "redirect_uri": redirect_uri,
        })
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Zoom OAuth</title></head>
<body>
  <p>Click the link below to authorize Zoom (meeting host should sign in).</p>
  <p><a href="{html_stdlib.escape(auth_url)}">Authorize Zoom</a></p>
  <p><small>Redirect URI: {html_stdlib.escape(redirect_uri)}</small></p>
</body></html>"""
    return (html, 200, {"Content-Type": "text/html; charset=utf-8"})


def _handle_callback(request):
    """Exchange code for tokens; optionally store refresh_token in GSM."""
    redirect_uri = _redirect_uri(request)
    args = getattr(request, "args", None) or {}
    code = args.get("code") if hasattr(args, "get") else None
    if not code:
        return ("Missing code", 400)
    if not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
        return ("Server misconfigured: missing Zoom credentials", 500)

    r = requests.post(
        "https://zoom.us/oauth/token",
        auth=(ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    if r.status_code != 200:
        return (f"Zoom token error: {r.status_code} {r.text[:500]}", 400)

    data = r.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return ("Zoom did not return a refresh_token", 400)

    stored = ""
    if GCP_PROJECT:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            parent = f"projects/{GCP_PROJECT}"
            try:
                client.get_secret(request={"name": f"{parent}/secrets/ZOOM_REFRESH_TOKEN"})
            except Exception:
                client.create_secret(
                    request={
                        "parent": parent,
                        "secret_id": "ZOOM_REFRESH_TOKEN",
                        "secret": {"replication": {"automatic": {}}},
                    }
                )
            client.add_secret_version(
                request={
                    "parent": f"{parent}/secrets/ZOOM_REFRESH_TOKEN",
                    "payload": {"data": refresh_token.encode("utf-8")},
                }
            )
            stored = f" Stored in Secret Manager: projects/{GCP_PROJECT}/secrets/ZOOM_REFRESH_TOKEN"
        except Exception as e:
            stored = f" (Could not store in GSM: {e})"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Zoom OAuth Success</title></head>
<body>
  <h2>Success</h2>
  <p>Refresh token received.{stored}</p>
  <p>Add ZOOM_REFRESH_TOKEN to your telehealth webhook deploy (from GSM) and redeploy.</p>
  <p><small>You can close this tab.</small></p>
</body></html>"""
    return (html, 200, {"Content-Type": "text/html; charset=utf-8"})

