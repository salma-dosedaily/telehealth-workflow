# MCP Service Account (Cross-Project: dosedaily-raw + dosedaily-prod)

Create a service account that has the **same permissions as salma.elmasry@dosedaily.co** on both `dosedaily-raw` and `dosedaily-prod`, for use with the BigQuery MCP server (and other GCP MCP tools) so Cursor can query both projects without re-auth issues.

## Prerequisites

- `gcloud` CLI installed and logged in as a user that can create service accounts and modify IAM (e.g. Owner or IAM Admin).
- Re-auth if you see `invalid_rapt` or "Reauthentication failed":
  ```bash
  gcloud auth login
  gcloud auth application-default login   # optional, for Application Default Credentials
  ```

## Steps

1. **List current roles (optional)**  
   The script will print the roles that `salma.elmasry@dosedaily.co` has in each project before creating the SA.

2. **Run the script** (from repo root):
   ```bash
   ./scripts/create_mcp_service_account_cross_project.sh
   ```
   - Dry run (only list roles, do not create or grant):
     ```bash
     ./scripts/create_mcp_service_account_cross_project.sh --dry-run
     ```

3. **What it does**
   - Reads IAM policy for `dosedaily-raw` and `dosedaily-prod`.
   - Collects all roles assigned to `salma.elmasry@dosedaily.co` in either project.
   - Creates service account `mcp-bigquery-cross@dosedaily-raw.iam.gserviceaccount.com` in `dosedaily-raw`.
   - Grants the **union** of those roles to the SA in **both** projects so the SA has the same access as the reference user in both.

4. **Using the service account with MCP**
   - **Option A – Key file (recommended for MCP)**  
     Key created at `$HOME/.config/mcp-bigquery-sa-key.json`. Set the env var so the MCP server uses it:
     ```bash
     export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/mcp-bigquery-sa-key.json"
     ```
     So Cursor’s MCP process sees it, either:
     - **Start Cursor from a terminal** after running the export above, or
     - **Add to your shell profile** (`~/.zshrc` or `~/.bash_profile`):
       ```bash
       export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/mcp-bigquery-sa-key.json"
       ```
       Then restart Cursor (or open a new terminal and launch Cursor from it).
     To create a new key later (e.g. after rotation):
     ```bash
     gcloud iam service-accounts keys create "$HOME/.config/mcp-bigquery-sa-key.json" \
       --iam-account=mcp-bigquery-cross@dosedaily-raw.iam.gserviceaccount.com \
       --project=dosedaily-raw
     ```
   - **Option B – Application Default Credentials (ADC)**  
     Impersonate or sign in as the SA (e.g. `gcloud auth application-default login` and choose the SA).
   - Your `~/.cursor/mcp.json` uses `npx -y @ergut/mcp-bigquery-server` with `--project-id dosedaily-raw`. With `GOOGLE_APPLICATION_CREDENTIALS` set to the key path, the MCP server will use this SA and can query both `dosedaily-raw` and `dosedaily-prod` (e.g. `dosedaily-raw.klaviyo.profile_v2` and `dosedaily-prod.dim_customers.v_customers`).

## Security

- Do not commit the key file. Add it to `.gitignore` (e.g. `*sa-key*.json`, `mcp-bigquery-sa-key.json`).
- Prefer ADC with short-lived credentials where possible; use key files only when the MCP server cannot use ADC.

## Reference

- MCP config: `~/.cursor/mcp.json` (BigQuery server uses `dosedaily-raw` and location `US`).
- Script: `scripts/create_mcp_service_account_cross_project.sh`.
