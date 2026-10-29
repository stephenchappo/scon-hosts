#!/usr/bin/env bash
# eddie's outside-in watchdog: is home still there? Runs every 5 minutes.
#
# Checks Homepage on Trillian (svc:home), Loki on Trillian, and whether Trillian and
# Deepthought are online on the tailnet. Pushes once when a check has failed twice in a
# row (about 10 minutes) and once when it recovers, as scon-push level "broken": high
# priority, never held for quiet hours. Posts straight to eddie's own ntfy, so it works
# when every home machine is off.
set -uo pipefail

NTFY=${WATCHDOG_NTFY:-http://127.0.0.1:8491/homelab}
STATE=${WATCHDOG_STATE:-$HOME/.local/state/eddie-watchdog}
mkdir -p "$STATE"

http_ok() { [ "$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$1")" = 200 ]; }
online() {
  tailscale status --json 2>/dev/null |
    jq -e --arg h "$1" '[.Peer[] | select(.DNSName | startswith($h + ".")) | .Online] | any' >/dev/null
}

push() {  # title, body
  curl -s -m 10 -o /dev/null \
    -H "Title: $1" -H "Priority: high" -H "Tags: rotating_light,broken" \
    -d "$2" "$NTFY" || true
}

check() {  # name, label, command...
  local name=$1 label=$2; shift 2
  local fails_file="$STATE/$name.fails" down_file="$STATE/$name.down"
  local fails; fails=$(cat "$fails_file" 2>/dev/null || echo 0)
  if "$@"; then
    echo 0 >"$fails_file"
    if [ -f "$down_file" ]; then
      push "Back: $label" "$label is answering again (down since $(cat "$down_file"))."
      rm -f "$down_file"
    fi
    echo "ok   $name"
  else
    fails=$((fails + 1)); echo "$fails" >"$fails_file"
    if [ "$fails" -ge 2 ] && [ ! -f "$down_file" ]; then
      date '+%a %H:%M' >"$down_file"
      push "Down: $label" "eddie can't reach $label (checked from outside the house, twice, 5 minutes apart)."
    fi
    echo "FAIL $name ($fails)"
  fi
}

check homepage "Homepage on Trillian" http_ok https://home.batfish-pride.ts.net
check loki "Loki on Trillian" http_ok http://trillian2-1.batfish-pride.ts.net:3100/ready
check trillian "Trillian (tailnet)" online trillian2-1
check deepthought "Deepthought (tailnet)" online deepthought
