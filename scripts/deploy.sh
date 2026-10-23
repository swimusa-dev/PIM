#!/usr/bin/env bash
# Build the React frontend into backend/pim/static, then deploy the bundle to the chosen target.
# Usage: scripts/deploy.sh [dev|prod]   (default dev). Requires: node 22, npm, databricks CLI >= 0.260 logged in.
set -euo pipefail
TARGET=${1:-dev}
cd "$(dirname "$0")/.."
echo ">> Building frontend"
(cd frontend && npm ci && npm run build)
test -f backend/pim/static/index.html || { echo "frontend build missing"; exit 1; }
echo ">> Validating bundle"
databricks bundle validate -t "$TARGET"
echo ">> Deploying bundle (jobs + app definition + source files)"
databricks bundle deploy -t "$TARGET"
echo ">> Starting / redeploying the app compute"
databricks bundle run pim_app -t "$TARGET"
echo ">> Done. Open the app URL printed above. First run: see docs/SETUP_AND_DEPLOY.md (seed + first ingest)."
