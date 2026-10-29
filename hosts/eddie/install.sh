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
