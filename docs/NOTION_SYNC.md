# Sync project documentation to Notion

This project can sync its documentation (all `docs/*.md` and `CHANGELOG.md`) into Notion as child pages under a page you choose.

## Security

- **Do not commit your Notion API key.** The script reads it from the environment only.
- If you ever pasted your API key in chat or in a file, **rotate it** in Notion: [My integrations](https://www.notion.so/profile/integrations) → your integration → regenerate or create a new key.

## Prerequisites

1. **Notion integration and API key**
   - Go to [Notion Integrations](https://www.notion.so/my-integrations) and create an integration (or use an existing one).
   - Copy the **Internal Integration Secret** (starts with `ntn_` or `secret_`). This is your `NOTION_API_KEY`.

2. **A parent page in Notion**
   - In Notion, create a page that will hold all doc pages (e.g. "Telehealth Workflow Docs").
   - Open that page and **share it with your integration**: click **…** → **Add connections** → select your integration.
   - Copy the **page ID** from the URL. The URL looks like:
     `https://www.notion.so/Workspace-Name-Page-Title-abc123def456...`
     The page ID is the last part (with or without dashes). Use it as `NOTION_PARENT_PAGE_ID`.

## Run the sync

From the project root, with a virtualenv activated and `requests` installed:

```bash
export NOTION_API_KEY="ntn_your_key_here"
export NOTION_PARENT_PAGE_ID="your-parent-page-id"
python scripts/sync_docs_to_notion.py
```

Or use a `.env` file (do not commit it):

```bash
# .env (add to .gitignore if not already)
NOTION_API_KEY=ntn_...
NOTION_PARENT_PAGE_ID=abc123def456...
```

Then:

```bash
set -a && source .env && set +a
python scripts/sync_docs_to_notion.py
```

The script creates one Notion page per file under the parent:

- **docs/** → one page per `.md` file (title derived from filename). Includes:
  - `KIM_QUICK_REFERENCE.md` — Kim's workflow guide (updated with No Show instructions)
  - `SETUP_STEP_BY_STEP.md` — full setup guide (updated with Klaviyo No Show split and Google Form steps)
  - All other docs (CHANGELOG, troubleshooting, Zoom fast path, etc.)
- **CHANGELOG.md** → one page titled "Changelog".

Content is sent as Notion-flavored Markdown. If the API returns an error (e.g. 403), ensure the parent page is shared with your integration and the integration has **Insert content** capability.

> **After the No Show feature deploy:** re-run the sync to push the updated `KIM_QUICK_REFERENCE.md` and `SETUP_STEP_BY_STEP.md` to Notion so Kim and the team have the latest instructions.

## Troubleshooting: 404 "Could not find page with ID..."

This means the integration cannot see the parent page. Fix it as follows:

1. **Confirm the parent is a page, not a database.** The script expects a **page** ID. If "Telehealth Workflow Docs" is a database (table view), the script would need to use a database parent instead; for now use a normal **empty page** as the parent.

2. **Create a new empty page and share it:**
   - In Notion, create a **new page** (click + New page). Name it e.g. "Telehealth Docs".
   - Open that page → click **Share** (top right).
   - Add your integration: search for **"Data Engineering Bot"** or **"Dose"** and add it (Full access).
   - Copy the **page ID** from the URL (e.g. `https://www.notion.so/.../abc123def456...` → use `abc123def456...`).
   - Run: `export NOTION_PARENT_PAGE_ID="that-id"` then `python scripts/sync_docs_to_notion.py`.

3. **If the integration doesn’t appear in Share:** Use the **⋯** menu on the page → **Connections** → **Manage connections** or **Add connection** and search for your integration. Add it there, then run the script again.
