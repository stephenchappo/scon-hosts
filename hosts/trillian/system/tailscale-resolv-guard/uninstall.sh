#!/bin/sh
set -eu
sudo rm -f /etc/systemd/system/tailscaled.service.d/resolv-guard.conf /usr/local/sbin/tailscale-resolv-guard
sudo rmdir /etc/systemd/system/tailscaled.service.d 2>/dev/null || true
sudo systemctl daemon-reload
