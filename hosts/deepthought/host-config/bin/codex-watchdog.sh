#!/bin/bash
LOG=/home/scon/.codex/remote-control.log
MAX_AGE=1800  # 30 minutes

if [ ! -f "$LOG" ]; then
    echo "$(date -u -Iseconds) [watchdog] log missing, restarting codex-remote-control" >> "$LOG"
    systemctl --user restart codex-remote-control.service
    exit 0
fi

AGE=$(( $(date +%s) - $(stat -c %Y "$LOG") ))
if [ "$AGE" -gt "$MAX_AGE" ]; then
    echo "$(date -u -Iseconds) [watchdog] log stale ${AGE}s, restarting codex-remote-control" >> "$LOG"
    systemctl --user restart codex-remote-control.service
fi
