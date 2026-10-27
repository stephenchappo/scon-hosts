#!/bin/sh
# Install the tailscaled resolv.conf guard. Root-owned copies, not symlinks:
# the script runs as root before tailscaled. Re-run after editing anything here.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
sudo install -o root -g root -m 0755 "$here/tailscale-resolv-guard" /usr/local/sbin/tailscale-resolv-guard
sudo install -d -o root -g root -m 0755 /etc/systemd/system/tailscaled.service.d
sudo install -o root -g root -m 0644 "$here/tailscaled-resolv-guard.conf" /etc/systemd/system/tailscaled.service.d/resolv-guard.conf
sudo systemctl daemon-reload
echo "installed; takes effect on the next tailscaled start"
