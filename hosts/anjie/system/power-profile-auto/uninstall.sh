#!/usr/bin/env bash
# Remove power-profile-auto from Anjie. Leaves the current profile as-is;
# power-profiles-daemon reverts to `balanced` on the next boot.
set -euo pipefail

[[ "$(id -u)" -ne 0 ]] || { echo "Run as your normal user, not root"; exit 1; }

sudo systemctl disable --now power-profile-auto.service || true
sudo rm -f /etc/systemd/system/power-profile-auto.service \
           /etc/udev/rules.d/99-power-profile-auto.rules \
           /usr/local/bin/power-profile-auto.sh
sudo systemctl daemon-reload
sudo udevadm control --reload-rules
echo "Removed."
