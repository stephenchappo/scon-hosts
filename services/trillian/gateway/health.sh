#!/usr/bin/env bash
# Health check for the gateway, autodeploy style: one line per check, non-zero on any failure.
# Usage: health.sh [expected-policy-digest]
set -u
URL=${GATEWAY_URL:-http://127.0.0.1:8640}
fail=0
h=$(curl -fsS --max-time 5 "$URL/healthz") || { echo "FAIL healthz unreachable"; exit 1; }
echo "$h" | python3 -c 'import json,sys; h=json.load(sys.stdin); sys.exit(0 if h["ok"] and not h["degraded"] else 1)' \
  && echo "ok   policy loaded, not degraded" || { echo "FAIL policy degraded or missing: $h"; fail=1; }
if [ -n "${1:-}" ]; then
  echo "$h" | grep -q "\"digest\": *\"$1\"" && echo "ok   serving digest $1" || { echo "FAIL not serving $1"; fail=1; }
fi
# Deny by default: no token must mean no service.
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST "$URL/v1/chat/completions" -d '{}')
[ "$code" = 401 ] && echo "ok   unauthenticated call refused" || { echo "FAIL unauthenticated call got $code"; fail=1; }
exit $fail
