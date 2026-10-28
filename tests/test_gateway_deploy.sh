#!/usr/bin/env bash
# Tests for services/trillian/gateway/deploy.sh and health.sh with a fake docker, a fake bws
# and a stub gateway. No containers start. Run: bash tests/test_gateway_deploy.sh
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); STUB=
trap '[ -n "$STUB" ] && kill $STUB; rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/home/.config/bws" "$T/home/.config/scon-gateway"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
SYS=${SYSTEM_CHECKOUT:-$ROOT/../scon-system}
git clone -q --bare "$SYS" "$T/system.git"
git -C "$T/system.git" update-ref refs/heads/main "$(git -C "$SYS" rev-parse HEAD)"
cat > "$T/bin/docker" <<'FAKE'
#!/usr/bin/env bash
case "$1" in
  build) exit 0 ;;
  image) exit 0 ;;
  run) [[ "$*" == *app.policy* ]] && echo '{"ok": true, "digest": "'"$DIGEST"'"}'; exit 0 ;;
  compose) env | grep -E '^GATEWAY_(IMAGE|RELEASE)=' > "$STATE" ;;
esac
FAKE
cat > "$T/bin/bws" <<'FAKE'
#!/usr/bin/env bash
shift 3; [ "$1" = "--" ] && shift; export OPENROUTER_API=x; exec "$@"
FAKE
cat > "$T/stub.py" <<'FAKE'
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
st = os.environ["STATE"]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        env = dict(l.strip().split("=", 1) for l in open(st)) if os.path.exists(st) else {}
        bad = os.path.exists(st + ".bad") and env.get("GATEWAY_IMAGE", "").endswith(open(st + ".bad").read().strip())
        b = json.dumps({"ok": True, "degraded": bad, "digest": "d1", "release": env.get("GATEWAY_RELEASE")}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(b)
    def do_POST(self): self.send_response(401); self.end_headers()
s = HTTPServer(("127.0.0.1", 0), H); print(s.server_port, flush=True); s.serve_forever()
FAKE
chmod +x "$T/bin/"*
printf 'gateway 1111\n' > "$T/projects.conf"; printf tok > "$T/home/.config/bws/gateway.token"
chmod 600 "$T/home/.config/bws/gateway.token"
export STATE=$T/state.env DIGEST=d1 PATH=$T/bin:$PATH HOME=$T/home SYSTEM_REMOTE=$T/system.git \
  BWS_PROJECTS_CONF=$T/projects.conf GATEWAY_DEPLOY_WAIT=0
coproc python3 "$T/stub.py"; STUB=$COPROC_PID; read -r port <&"${COPROC[0]}"
export GATEWAY_URL=http://127.0.0.1:$port
cp -r "$ROOT" "$T/hosts"; rm -f "$T/hosts/services/trillian/gateway/compose.override.yaml"
H=$T/hosts/services/trillian/gateway; B=$T/home/.local/share/scon-gateway
commit() { echo "# $1" >> "$H/README.md"; git -C "$T/hosts" commit -qam "test $1"; }
pass=0; fail=0
ok() { if eval "$2"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1"; fi; }

ok "staged: refuses to deploy without the LIVE marker" '! bash "$H/deploy.sh" >/dev/null 2>&1 && [ ! -f "$STATE" ]'
ok "--check passes and starts nothing" 'bash "$H/deploy.sh" --check >/dev/null 2>&1 && [ ! -f "$STATE" ]'
touch "$T/home/.config/scon-gateway/LIVE"
commit one; bash "$H/deploy.sh" >/dev/null 2>&1; r1=$(cat "$B/current")
ok "deploy records a release of both commits and runs its image" \
  'grep -q "^IMAGE=scon-gateway:$(git -C "$T/hosts" rev-parse HEAD | cut -c1-12)" "$B/releases/$r1.env" && grep -q "GATEWAY_RELEASE=$r1" "$STATE"'
commit two; bash "$H/deploy.sh" >/dev/null 2>&1; r2=$(cat "$B/current")
ok "a second deploy keeps the first as last-known-good" '[ "$r2" != "$r1" ] && [ "$(cat "$B/lkg")" = "$r1" ]'
ok "rollback runs the old image and tables" 'bash "$H/deploy.sh" --rollback >/dev/null 2>&1 && grep -q "GATEWAY_RELEASE=$r1" "$STATE"'
commit three; git -C "$T/hosts" rev-parse HEAD | cut -c1-12 > "$STATE.bad"
ok "an unhealthy release is restored to the previous one" '! bash "$H/deploy.sh" >/dev/null 2>&1 && grep -q "GATEWAY_RELEASE=$r1" "$STATE" && [ "$(cat "$B/current")" = "$r1" ]'
rm -f "$STATE.bad"
ok "a release not serving its own policy digest is restored" '! DIGEST=d2 bash "$H/deploy.sh" >/dev/null 2>&1 && grep -q "GATEWAY_RELEASE=$r1" "$STATE"'
echo x >> "$H/README.md"
ok "uncommitted code is never deployed" '! bash "$H/deploy.sh" --check >/dev/null 2>&1'
git -C "$T/hosts" checkout -q -- .
exec 8>"$B/deploy.lock"; flock 8
ok "one deploy at a time" 'bash "$H/deploy.sh" --check 2>&1 | grep -q "another deploy"'
exec 8>&-

echo "$pass passed, $fail failed"; [ $fail = 0 ]
