#!/usr/bin/env bash
# gw-token: format, verifier matches, refuses pipes and bad ids.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd); pass=0; fail=0
ok() { if eval "$2"; then pass=$((pass+1)); else echo "FAIL: $1"; fail=$((fail+1)); fi; }
out=$(GW_TOKEN_ALLOW_PIPE=1 "$HERE/bin/gw-token" new consolidation-cloud)
tok=$(echo "$out" | grep -oE 'gw\.consolidation-cloud\.[A-Za-z0-9_-]{43,}' | head -1)
ver=$(echo "$out" | sed -n 's/^ *Value: //p')
ok "token has the gw.<id>.<43+> shape" '[ -n "$tok" ]'
ok "verifier name follows the id" 'echo "$out" | grep -q "Name:  GW_TOKEN_SHA256_CONSOLIDATION_CLOUD"'
ok "verifier is sha256 of the token" '[ "$ver" = "$(printf %s "$tok" | sha256sum | cut -d" " -f1)" ]'
ok "refuses a pipe" '! "$HERE/bin/gw-token" new x >/dev/null 2>&1'
ok "refuses a bad id" '! GW_TOKEN_ALLOW_PIPE=1 "$HERE/bin/gw-token" new "Bad_ID" >/dev/null 2>&1'
ok "two tokens differ" '[ "$tok" != "$(GW_TOKEN_ALLOW_PIPE=1 "$HERE/bin/gw-token" new consolidation-cloud | grep -oE "gw\.consolidation-cloud\.[A-Za-z0-9_-]{43,}" | head -1)" ]'
echo "$pass passed, $fail failed"; [ $fail = 0 ]
