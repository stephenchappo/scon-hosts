#!/bin/bash
# Select the power profile according to AC presence.
#
# Installed to /usr/local/bin/power-profile-auto.sh (root-owned, 0755).
# Run by power-profile-auto.service, triggered at boot and by the udev rule
# on AC plug/unplug.
#
# CAVEAT: setting `performance` is frequently a no-op. Whenever
# power-profiles-daemon reports PerformanceDegraded: lap-detected, the EC caps
# the package at the 15 W PL1 no matter which profile is selected. See README.md.
set -u

AC=/sys/class/power_supply/AC/online

if [ "$(cat "$AC" 2>/dev/null)" = "1" ]; then
    exec /usr/bin/powerprofilesctl set performance
else
    exec /usr/bin/powerprofilesctl set balanced
fi
