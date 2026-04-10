#!/usr/bin/env bash
# Create a service account with same permissions as salma.elmasry@dosedaily.co
# on both dosedaily-raw and dosedaily-prod (for MCP BigQuery cross-project access).
#
# Prerequisites:
#   gcloud auth login
#   gcloud auth application-default login  # optional, for ADC
#
# Usage:
#   ./scripts/create_mcp_service_account_cross_project.sh [--dry-run]

set -euo pipefail

REFERENCE_USER="salma.elmasry@dosedaily.co"
PROJECT_RAW="dosedaily-raw"
PROJECT_PROD="dosedaily-prod"
SA_NAME="mcp-bigquery-cross"
SA_EMAIL="${SA_NAME}@${PROJECT_RAW}.iam.gserviceaccount.com"
DRY_RUN=false

for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN=true
  fi
done

echo "=== Reference user: ${REFERENCE_USER} ==="
echo "=== Projects: ${PROJECT_RAW}, ${PROJECT_PROD} ==="
echo "=== Service account to create: ${SA_EMAIL} ==="
echo ""

# --- 1) List roles for reference user in both projects ---
list_roles_in_project() {
  local project=$1
  gcloud projects get-iam-policy "$project" --format="json" 2>/dev/null | \
    python3 -c "
import json, sys
d = json.load(sys.stdin)
for b in d.get('bindings', []):
    for m in b.get('members', []):
        if 'salma.elmasry@dosedaily.co' in m:
            print(b['role'])
"
}

echo "--- Roles for ${REFERENCE_USER} in ${PROJECT_RAW} ---"
ROLES_RAW=$(list_roles_in_project "$PROJECT_RAW" | sort -u) || true
echo "${ROLES_RAW:- (none or unable to list)}"

echo ""
echo "--- Roles for ${REFERENCE_USER} in ${PROJECT_PROD} ---"
ROLES_PROD=$(list_roles_in_project "$PROJECT_PROD" | sort -u) || true
echo "${ROLES_PROD:- (none or unable to list)}"

# Collect all unique roles across both projects to grant to the SA
ALL_ROLES=$( (echo "$ROLES_RAW"; echo "$ROLES_PROD") | sort -u | grep -v '^$' || true)
if [[ -z "${ALL_ROLES:-}" ]]; then
  echo ""
  echo "No roles found for ${REFERENCE_USER}. You may need to run: gcloud auth login"
  echo "If the user has permissions via a group, list that group's roles and set ALL_ROLES in this script."
  echo "Common roles for BigQuery + MCP: roles/bigquery.admin, roles/bigquery.dataViewer, roles/bigquery.jobUser"
  exit 1
fi

echo ""
echo "--- Roles to grant to ${SA_EMAIL} (union of both projects) ---"
echo "$ALL_ROLES"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
  echo "Dry run: would create SA and grant the above roles. Exiting."
  exit 0
fi

# --- 2) Create service account in dosedaily-raw ---
echo "--- Creating service account in ${PROJECT_RAW} ---"
if gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_RAW" &>/dev/null; then
  echo "Service account ${SA_EMAIL} already exists."
else
  gcloud iam service-accounts create "$SA_NAME" \
    --project="$PROJECT_RAW" \
    --display-name="MCP BigQuery cross-project (same as ${REFERENCE_USER})"
  echo "Created ${SA_EMAIL}"
fi

# --- 3) Grant each role to the SA in the project(s) where the user has it ---
grant_sa_role() {
  local project=$1
  local role=$2
  echo "  Granting ${role} in ${project} to ${SA_EMAIL}"
  gcloud projects add-iam-policy-binding "$project" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$role" \
    --condition=None \
    --quiet
}

echo ""
echo "--- Granting union of roles to ${SA_EMAIL} in both projects ---"
for role in $ALL_ROLES; do
  grant_sa_role "$PROJECT_RAW" "$role"
  grant_sa_role "$PROJECT_PROD" "$role"
done

echo ""
echo "=== Done. Service account: ${SA_EMAIL} ==="
echo "To use with MCP BigQuery (e.g. ADC):"
echo "  gcloud auth application-default login"
echo "  # Or for SA key: gcloud iam service-accounts keys create key.json --iam-account=${SA_EMAIL}"
echo "To point MCP to this SA, set GOOGLE_APPLICATION_CREDENTIALS to the key path or use ADC after 'gcloud auth application-default login' with this account."
echo "For @ergut/mcp-bigquery-server you can pass --project-id dosedaily-raw (default) and query both projects; the SA now has access to both."
