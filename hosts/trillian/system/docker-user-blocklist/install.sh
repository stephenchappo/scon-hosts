#!/bin/sh
# Install the DOCKER-USER blocklist. Root-owned copies, not symlinks.
# Re-run after editing anything here.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
sudo install -o root -g root -m 0755 "$here/docker-user-blocklist" /usr/local/sbin/docker-user-blocklist
sudo install -o root -g root -m 0644 "$here/blocklist" /etc/docker-user-blocklist
sudo install -o root -g root -m 0644 "$here/docker-user-blocklist.service" /etc/systemd/system/docker-user-blocklist.service
sudo systemctl daemon-reload
sudo systemctl enable docker-user-blocklist.service
sudo systemctl restart docker-user-blocklist.service
echo "installed; rules now:"
sudo iptables -S DOCKER-USER
