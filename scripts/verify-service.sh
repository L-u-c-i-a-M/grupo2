#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${1:-http://127.0.0.1:${APP_PORT:-8101}}"
echo "== OpsCenter verification =="
echo "Target: $BASE_URL"
check(){ local label="$1"; local endpoint="$2"; echo "[$label] $endpoint"; curl -fsS "$BASE_URL$endpoint"; echo; }
check "1/4 Liveness" "/live"
check "2/4 Readiness" "/ready"
check "3/4 Health" "/health"
check "4/4 Version" "/version"
echo "SERVICE HEALTHY"
