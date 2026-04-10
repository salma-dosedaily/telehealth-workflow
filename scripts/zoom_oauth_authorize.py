#!/usr/bin/env python3
"""
One-time Zoom OAuth 2.0 authorization for General App (when Server-to-Server is not available).
Run locally; opens browser for the meeting host to authorize; stores refresh_token for the fast path.

Prereqs:
  - Create a "General App" in Zoom Marketplace (not Webhook-only).
  - Add Redirect URL: http://127.0.0.1:8765/callback
  - Add scope: recording:read (or recording:read:admin)
  - Set ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET (env or .env)

Usage:
  python scripts/zoom_oauth_authorize.py
  # Optional: save to GSM
  python scripts/zoom_oauth_authorize.py --project dosedaily-raw
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

# Load .env if present (project root)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

REDIRECT_PORT = 8765
SCOPE = "recording:read"  # User's cloud recordings (for polling transcript)


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time Zoom OAuth: get refresh token for fast path")
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT"), help="GCP project to store ZOOM_REFRESH_TOKEN in Secret Manager")
    parser.add_argument("--redirect-uri", default=os.environ.get("ZOOM_REDIRECT_URI"), help="HTTPS redirect URI (e.g. from ngrok: https://abc123.ngrok.io/callback). Required when Zoom rejects http://127.0.0.1")
    args = parser.parse_args()

    client_id = os.environ.get("ZOOM_CLIENT_ID", "").strip()
    client_secret = os.environ.get("ZOOM_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("Set ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET (from Zoom General App) in env or .env", file=sys.stderr)
        sys.exit(1)

    if args.redirect_uri:
        redirect_uri = args.redirect_uri.rstrip("/")
        if not redirect_uri.endswith("/callback"):
            redirect_uri = redirect_uri + "/callback"
        print("Using redirect URI:", redirect_uri)
    else:
        redirect_uri = f"http://127.0.0.1:{REDIRECT_PORT}/callback"

    auth_url = (
        "https://zoom.us/oauth/authorize?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
        })
    )

    code_holder: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if not self.path.startswith("/callback"):
                self.send_response(404)
                self.end_headers()
                return
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            code = (qs.get("code") or [None])[0]
            if code:
                code_holder.append(code)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Authorization received. You can close this tab and return to the terminal."
            self.wfile.write(f"<html><body><p>{msg}</p></body></html>".encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    if args.redirect_uri:
        print(f"1. In another terminal run: ngrok http {REDIRECT_PORT}")
        print(f"2. Add this Redirect URL in Zoom (must match exactly): {redirect_uri}")
        print(f"3. Open this URL in your browser (meeting host signs in):")
    else:
        print(f"1. Add this Redirect URL in your Zoom General App: {redirect_uri}")
        print(f"2. Open this URL in your browser (meeting host should sign in and authorize):")
    print(auth_url)
    print("\nWaiting for callback ...")
    try:
        server.handle_request()
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        sys.exit(1)

    if not code_holder:
        print("No authorization code received. Did you approve the app and get redirected?", file=sys.stderr)
        sys.exit(1)

    code = code_holder[0]
    import requests
    r = requests.post(
        "https://zoom.us/oauth/token",
        auth=(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print("Zoom did not return a refresh_token.", file=sys.stderr)
        sys.exit(1)

    print("\nRefresh token (store as ZOOM_REFRESH_TOKEN in env or Secret Manager):")
    print(refresh_token)

    if args.project:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            parent = f"projects/{args.project}"
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
            print(f"\nStored in Google Secret Manager: projects/{args.project}/secrets/ZOOM_REFRESH_TOKEN")
            print("Grant the Cloud Function's service account access: roles/secretmanager.secretAccessor (and secretVersionAdder if you want the function to rotate the token).")
        except Exception as e:
            print(f"\nCould not store in GSM: {e}", file=sys.stderr)
    else:
        print("\nTo store in GSM, run again with --project YOUR_GCP_PROJECT")


if __name__ == "__main__":
    main()
