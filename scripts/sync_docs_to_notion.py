#!/usr/bin/env python3
"""
Sync project documentation (docs/*.md and CHANGELOG) to Notion as child pages.

Uses NOTION_API_KEY and NOTION_PARENT_PAGE_ID from the environment. Never commit
the API key; use .env or export. Create a page in Notion, share it with your
integration, and use its ID (from the URL) as NOTION_PARENT_PAGE_ID.

Usage:
  export NOTION_API_KEY="ntn_..."
  export NOTION_PARENT_PAGE_ID="your-page-id-from-notion-url"
  python scripts/sync_docs_to_notion.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

import requests

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-02-22"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _normalize_page_id(page_id: str) -> str:
    """Remove dashes so Notion accepts the ID."""
    return re.sub(r"-", "", page_id.strip())


def check_parent_access(token: str, parent_page_id: str) -> bool:
    """Verify the integration can access the parent page. Returns False on 404 or error."""
    parent_id = _normalize_page_id(parent_page_id)
    resp = requests.get(
        f"{NOTION_API_BASE}/pages/{parent_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
        },
        timeout=15,
    )
    if resp.ok:
        return True
    if resp.status_code == 404:
        logger.error(
            "Parent page not found or not shared with your integration. "
            "Open the page in Notion → Share → add your integration (Data Engineering Bot / Dose). "
            "Use the page ID from that page's URL (last segment). If the parent is a database, use NOTION_PARENT_DATABASE_ID instead (see docs/NOTION_SYNC.md)."
        )
    else:
        logger.error("Notion API error %s: %s", resp.status_code, resp.text[:300])
    return False


def _load_docs(project_root: Path) -> list[tuple[str, str, str]]:
    """Return list of (title, filename, markdown_content)."""
    docs_dir = project_root / "docs"
    changelog = project_root / "CHANGELOG.md"
    out = []

    if docs_dir.is_dir():
        for f in sorted(docs_dir.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Skip %s: %s", f.name, e)
                continue
            title = f.stem.replace("-", " ").replace("_", " ").title()
            out.append((title, f.name, text))

    if changelog.is_file():
        try:
            text = changelog.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Skip CHANGELOG: %s", e)
        else:
            out.append(("Changelog", "CHANGELOG.md", text))

    return out


def create_page(
    token: str,
    parent_page_id: str,
    title: str,
    markdown: str,
) -> dict | None:
    """Create one Notion page under parent with title and markdown content."""
    parent_id = _normalize_page_id(parent_page_id)
    # Notion expects newlines as \n in JSON
    markdown_escaped = markdown.replace("\r\n", "\n").replace("\r", "\n")

    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {
            "title": [{"text": {"content": title[:2000]}}],
        },
        "markdown": markdown_escaped,
    }

    resp = requests.post(
        f"{NOTION_API_BASE}/pages",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        },
        json=payload,
        timeout=30,
    )

    if not resp.ok:
        logger.error("Notion API error %s: %s", resp.status_code, resp.text[:500])
        return None

    return resp.json()


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    token = (os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN") or "").strip()
    parent_id = (os.environ.get("NOTION_PARENT_PAGE_ID") or "").strip()

    if not token:
        logger.error("Set NOTION_API_KEY or NOTION_TOKEN in the environment.")
        return 1
    if not parent_id:
        logger.error(
            "Set NOTION_PARENT_PAGE_ID to the Notion page ID (from the page URL) under which to create doc pages."
        )
        return 1

    docs = _load_docs(project_root)
    if not docs:
        logger.error("No docs found under docs/ or CHANGELOG.md")
        return 1

    logger.info("Checking parent page access...")
    if not check_parent_access(token, parent_id):
        return 1

    created = 0
    for title, filename, content in docs:
        logger.info("Creating page: %s", title)
        page = create_page(token, parent_id, title, content)
        if page:
            created += 1
            url = page.get("url") or "(no url)"
            logger.info("  -> %s", url)

    logger.info("Done. Created %s of %s pages.", created, len(docs))
    return 0 if created == len(docs) else 1


if __name__ == "__main__":
    sys.exit(main())
