# power-profile-auto (Anjie)

Sets `performance` on AC and `balanced` on battery, at boot and on every AC
plug/unplug. Installed 2026-09-14.

| File | Installed to |
|---|---|
| `power-profile-auto.sh` | `/usr/local/bin/power-profile-auto.sh` (root, 0755) |
| `power-profile-auto.service` | `/etc/systemd/system/` (oneshot, `WantedBy=multi-user.target`) |
| `99-power-profile-auto.rules` | `/etc/udev/rules.d/` |

Install with `bash install.sh`, remove with `bash uninstall.sh`. Both run as your
normal user and call `sudo` themselves.

These are **copies, not symlinks** — deliberately. The script is executed as root by
systemd, so it must not sit in a user-writable path. Same reasoning as the Marvin
wrapper in `homelab-health/contrib/marvin/`.

## Read this before trusting it

**It is frequently a no-op.** Anjie is an X1 Carbon Gen 8 with a 15 W i7-10610U.
Whenever power-profiles-daemon reports `PerformanceDegraded: lap-detected`, the EC
caps the package at the 15 W PL1 regardless of which profile is selected. The ThinkPad
lap sensor (`/sys/devices/platform/thinkpad_acpi/dytc_lapmode`) toggles between `0`
and `1` on its own, on a hard desk, so this happens often and unpredictably.

Measured 2026-09-14, sustained all-core load:

| state | sustained |
|---|---|
| not degraded | ~24.96 W / 2850-2950 MHz, reaches 90-93 degC |
| degraded | 14.0-14.4 W / ~2000 MHz |

That is roughly a 45% sustained clock difference.

**The controlling variable is ppd's `PerformanceDegraded`, not `dytc_lapmode`.** The
degradation trails the sensor by tens of seconds; a run with `lapmode=1` but the
property still empty sustained the full 24.96 W. Check the property, not the sysfs file:

    busctl get-property net.hadess.PowerProfiles /net/hadess/PowerProfiles \
        net.hadess.PowerProfiles PerformanceDegraded

**Forcing RAPL does not work — do not retry it.** Writing 25 W to
`/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw` reads back as 25 W, but
the EC reverts it to 15 W and power still collapses to ~14 W mid-load. Tested
2026-09-14 with the sensor state held constant.

Suspend/resume clears the latch, but it returns within minutes.

## Unresolved

The lap sensor trips on a hard desk and `palmsensor` reads `1` essentially
permanently, which looks more like a failing proximity sensor than a surface
problem. Two untested avenues: a Lenovo BIOS setting (BIOS is N2WET52W 1.42,
2026-04-09, already current), or a warranty service call.

Sustained 25 W does thermal-throttle this chassis — a 35 s run at 93 degC moved the
throttle counters by core +151 / package +552. Expect an audible fan and a hot
chassis whenever the profile actually takes effect.
