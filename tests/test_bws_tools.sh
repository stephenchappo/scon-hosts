#!/usr/bin/env bash
# Tests for bin/bws-run, bin/secrets-readback and bin/secrets-backup against a fake bws.
# No network, no real Secrets Manager. Run: bash tests/test_bws_tools.sh
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/tok" "$T/meta"
cat > "$T/bin/bws" <<'FAKE'
#!/usr/bin/env bash
[ "${BWS_ACCESS_TOKEN:-}" = "machine-token" ] || { echo "bad token" >&2; exit 9; }
if [ "$1" = run ]; then shift 3; [ "$1" = "--" ] && shift; export OPENROUTER_API=or-value N8N_KEY=n8n-value; exec "$@"; fi
if [ "$1 $2" = "secret list" ]; then echo '[{"key":"OPENROUTER_API","value":"or-value"},{"key":"N8N_KEY","value":"n8n-value"}]'; fi
FAKE
chmod +x "$T/bin/bws"
printf 'gateway  1111-2222\nempty TBD\n' > "$T/projects.conf"
printf 'machine-token' > "$T/tok/gateway.token"; chmod 600 "$T/tok/gateway.token"
export PATH="$T/bin:$PATH" BWS_PROJECTS_CONF="$T/projects.conf" BWS_TOKEN_DIR="$T/tok"
pass=0; fail=0
ok() { if eval "$2"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1"; fi; }

out=$("$ROOT/bin/bws-run" gateway -- sh -c 'echo "$OPENROUTER_API ${BWS_ACCESS_TOKEN:-unset}"')
ok "injects secrets, hides the machine token" '[ "$out" = "or-value unset" ]'
ok "unknown project refused" '! "$ROOT/bin/bws-run" nope -- true 2>/dev/null'
ok "usage without --" '! "$ROOT/bin/bws-run" gateway true 2>/dev/null'
chmod 644 "$T/tok/gateway.token"
ok "loose token file refused" '! "$ROOT/bin/bws-run" gateway -- true 2>/dev/null'
chmod 600 "$T/tok/gateway.token"

printf 'OPENROUTER_API=or-value\n| `N8N_KEY` | n8n-value |\n' > "$T/old.md"
ok "readback passes when every value matches" '"$ROOT/bin/secrets-readback" gateway "$T/old.md" >/dev/null'
printf 'OPENROUTER_API=old-value\n' > "$T/old2.md"
r=$("$ROOT/bin/secrets-readback" gateway "$T/old2.md"); 
ok "readback fails on a changed value" '! "$ROOT/bin/secrets-readback" gateway "$T/old2.md" >/dev/null'
ok "readback never prints values" '! grep -q -e old-value -e or-value <<<"$r"'
printf 'EXTRA_KEY=x\nsome prose that is not a secret line\n' > "$T/old3.md"
r3=$("$ROOT/bin/secrets-readback" gateway "$T/old3.md")
ok "readback fails on a missing name and lists unparsed lines" '! "$ROOT/bin/secrets-readback" gateway "$T/old3.md" >/dev/null && grep -q MISSING <<<"$r3" && grep -q SKIPPED <<<"$r3"'

printf 'OPENROUTER_API=or-value\nOPENROUTER_API=old-value\n' > "$T/dup.md"
ok "readback fails on a duplicated name" '! "$ROOT/bin/secrets-readback" gateway "$T/dup.md" >/dev/null'
printf "OPENROUTER_API='or-value\n" > "$T/q.md"
ok "readback keeps an unmatched quote" '! "$ROOT/bin/secrets-readback" gateway "$T/q.md" >/dev/null'
printf '| Name | Value |\n|---|---|\n| `N8N_KEY` | n8n-value |\n| namespace_token | x |\n' > "$T/tbl.md"
r4=$("$ROOT/bin/secrets-readback" gateway "$T/tbl.md")
ok "readback checks a row whose name starts with name" 'grep -q "MISSING.*namespace_token" <<<"$r4"'
tr=$(env SHELLOPTS=xtrace bash -x "$ROOT/bin/bws-run" gateway -- true 2>&1)
ok "bws-run never traces the token" '! grep -q machine-token <<<"$tr"'
chmod 644 "$T/tok/gateway.token"
ok "readback refuses a loose token file" '! "$ROOT/bin/secrets-readback" gateway "$T/old.md" >/dev/null 2>&1'
chmod 600 "$T/tok/gateway.token"

age-keygen -o "$T/key.txt" 2>/dev/null; age-keygen -y "$T/key.txt" > "$T/meta/recipients.txt"
SECRETS_META_DIR="$T/meta" "$ROOT/bin/secrets-backup" gateway >/dev/null
f=$(ls "$T"/meta/bws-gateway-*.json.age 2>/dev/null | head -1)
ok "backup is age-encrypted and decrypts to the values" '[ -n "$f" ] && ! grep -q or-value "$f" && age -d -i "$T/key.txt" "$f" | grep -q "\"OPENROUTER_API\": \"or-value\""'
ok "backup refuses a TBD project" '! SECRETS_META_DIR="$T/meta" "$ROOT/bin/secrets-backup" empty 2>/dev/null'

echo "$pass passed, $fail failed"; [ $fail = 0 ]
