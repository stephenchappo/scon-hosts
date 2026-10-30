#!/usr/bin/env bash
# Runs ON eddie as scon (deploy.sh copies this folder to ~/eddie and calls it).
# Idempotent: re-run after any change under services/.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

# ntfy, published to the tailnet at https://eddie.batfish-pride.ts.net
cd "$HERE/services/ntfy"
docker compose up -d --pull missing
sudo tailscale serve --bg --https=443 http://127.0.0.1:8491 >/dev/null
for i in $(seq 1 30); do
  curl -fsS -m 3 http://127.0.0.1:8491/v1/health 2>/dev/null | grep -q '"healthy":true' && break
  sleep 2
done
curl -fsS -m 3 http://127.0.0.1:8491/v1/health | grep -q '"healthy":true' || { echo "ntfy not healthy" >&2; exit 1; }
echo "ntfy: healthy, served on https://eddie.batfish-pride.ts.net"

# Watchdog timer (user unit; linger is on from cloud-init)
mkdir -p ~/.config/systemd/user
install -m 644 "$HERE/services/watchdog/eddie-watchdog.service" "$HERE/services/watchdog/eddie-watchdog.timer" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now eddie-watchdog.timer
echo "watchdog: timer enabled"

# Browser Claude can drive: Playwright MCP's headless Chromium behind the scon-fetch proxy.
# MCP server on eddie's localhost only: http://127.0.0.1:8931/mcp (services/browser/README.md)
mkdir -p ~/.local/state/scon-fetch
cd "$HERE/services/browser"
SCON_UID=$(id -u) docker compose up -d --pull missing
sleep 5
docker compose exec -T browser node -e "require('net').connect({host:'1.1.1.1',port:443,timeout:5000}).on('connect',()=>process.exit(1)).on('error',()=>process.exit(0)).on('timeout',()=>process.exit(0))" \
  || { echo "browser: can reach the internet without the proxy" >&2; exit 1; }
python3 "$HERE/services/browser/smoke.py"
