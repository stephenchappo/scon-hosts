#!/usr/bin/env bash
# Health check for the gateway, autodeploy style: one line per check, non-zero on any failure.
# Usage: health.sh [expected-policy-digest] [expected-release]
set -u
URL=${GATEWAY_URL:-http://127.0.0.1:8640}
fail=0
h=$(curl -fsS --max-time 5 "$URL/healthz") || { echo "FAIL healthz unreachable or not ok"; exit 1; }
field() { echo "$h" | python3 -c 'import json,sys; v=json.load(sys.stdin).get(sys.argv[1]); print("" if v is None else v)' "$1"; }
[ "$(field ok)" = True ] && [ "$(field degraded)" = False ] \
  && echo "ok   policy loaded, not degraded" || { echo "FAIL policy degraded or missing: $h"; fail=1; }
if [ -n "${1:-}" ]; then
  [ "$(field digest)" = "$1" ] && echo "ok   serving policy $1" || { echo "FAIL not serving policy $1"; fail=1; }
fi
if [ -n "${2:-}" ]; then
  [ "$(field release)" = "$2" ] && echo "ok   running release $2" || { echo "FAIL not running release $2"; fail=1; }
fi
# Deny by default: no token must mean no service.
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST "$URL/v1/chat/completions" -d '{}')
[ "$code" = 401 ] && echo "ok   unauthenticated call refused" || { echo "FAIL unauthenticated call got $code"; fail=1; }
exit $fail
