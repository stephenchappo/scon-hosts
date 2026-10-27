#!/usr/bin/env bash
# Install power-profile-auto on Anjie.
#
# Run as your normal user (NOT root):
#   bash install.sh
#
# Installs COPIES, not symlinks. The script runs as root via systemd, so it must
# not live in a user-writable path — a symlink into ~/work would let any process
# running as scon rewrite a root-executed script. The Marvin wrapper in
# homelab-health/contrib/marvin uses copies for the same reason.
#
# Re-running is safe. After editing any file here, re-run this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ "$(id -u)" -ne 0 ]] || { echo "Run as your normal user, not root"; exit 1; }

echo "=== Installing power-profile-auto ==="

echo "[1/4] Installing the script"
sudo install -o root -g root -m 0755 \
    "${SCRIPT_DIR}/power-profile-auto.sh" /usr/local/bin/power-profile-auto.sh

echo "[2/4] Installing the unit and udev rule"
sudo install -o root -g root -m 0644 \
    "${SCRIPT_DIR}/power-profile-auto.service" /etc/systemd/system/power-profile-auto.service
sudo install -o root -g root -m 0644 \
    "${SCRIPT_DIR}/99-power-profile-auto.rules" /etc/udev/rules.d/99-power-profile-auto.rules

echo "[3/4] Reloading systemd and udev"
sudo systemctl daemon-reload
sudo udevadm control --reload-rules

echo "[4/4] Enabling and running once"
sudo systemctl enable --now power-profile-auto.service

echo
echo "=== Installed ==="
echo "  enabled: $(systemctl is-enabled power-profile-auto.service)"
echo "  profile: $(powerprofilesctl get)"
echo "  AC:      $(cat /sys/class/power_supply/AC/online)"
printf '  degraded: '
busctl get-property net.hadess.PowerProfiles /net/hadess/PowerProfiles \
    net.hadess.PowerProfiles PerformanceDegraded 2>/dev/null || echo '(unknown)'
