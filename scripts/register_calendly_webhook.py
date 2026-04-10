#!/usr/bin/env python3
"""
Register Calendly webhook subscription pointing to the Calendly Cloud Function.
Run after deploying the Calendly webhook Cloud Function. Requires CALENDLY_PERSONAL_ACCESS_TOKEN.

Usage:
  # From env:
  CALENDLY_PERSONAL_ACCESS_TOKEN=your_token python scripts/register_calendly_webhook.py --url https://YOUR_CF_URL.run.app

  # From Google Secret Manager (project dosedaily-raw):
  python scripts/register_calendly_webhook.py --url https://YOUR_CF_URL.run.app --from-secret-manager
  # Or set GCP_PROJECT and use --from-secret-manager
"""
import argparse
import os
import subprocess
import sys
import requests


def get_token_from_secret_manager(project: str = "dosedaily-raw") -> str:
    """Load CALENDLY_PERSONAL_ACCESS_TOKEN from Google Secret Manager."""
    try:
        out = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                "--secret=CALENDLY_PERSONAL_ACCESS_TOKEN",
                f"--project={project}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return (out.stdout or "").strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"Cannot read secret from Secret Manager: {e}", file=sys.stderr)
        return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Cloud Function URL (e.g. https://xxx.run.app)")
    parser.add_argument("--scope", default="organization", choices=["user", "organization"])
    parser.add_argument(
        "--from-secret-manager",
        action="store_true",
        help="Load CALENDLY_PERSONAL_ACCESS_TOKEN from Google Secret Manager (project from GCP_PROJECT or dosedaily-raw)",
    )
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT", "dosedaily-raw"), help="GCP project for Secret Manager")
    args = parser.parse_args()

    token = os.environ.get("CALENDLY_PERSONAL_ACCESS_TOKEN")
    if not token and args.from_secret_manager:
        token = get_token_from_secret_manager(project=args.project)
    if not token:
        print("Set CALENDLY_PERSONAL_ACCESS_TOKEN or use --from-secret-manager", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Get current user to find organization or user URI
    me = requests.get("https://api.calendly.com/users/me", headers=headers, timeout=10)
    me.raise_for_status()
    resource = me.json().get("resource", {})
    user_uri = resource.get("uri", "")
    org = resource.get("current_organization")
    org_uri = org if isinstance(org, str) else (org.get("uri", "") if isinstance(org, dict) else "")

    scope_key = "organization" if args.scope == "organization" else "user"
    scope_value = org_uri if scope_key == "organization" and org_uri else user_uri

    body = {
        "url": args.url.rstrip("/"),
        "events": ["invitee.created", "invitee.canceled"],
        scope_key: scope_value,
        "scope": args.scope,
    }

    resp = requests.post(
        "https://api.calendly.com/webhook_subscriptions",
        headers=headers,
        json=body,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    print("Webhook subscription created:", data.get("resource", {}).get("uri", ""))
    return 0


if __name__ == "__main__":
    exit(main())
