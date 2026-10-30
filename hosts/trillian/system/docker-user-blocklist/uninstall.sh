#!/bin/sh
# Remove the unit and script. Rules already in DOCKER-USER stay until the next
# Docker restart or reboot.
set -eu
sudo systemctl disable --now docker-user-blocklist.service || true
sudo rm -f /etc/systemd/system/docker-user-blocklist.service /usr/local/sbin/docker-user-blocklist /etc/docker-user-blocklist
sudo systemctl daemon-reload
echo "removed"
