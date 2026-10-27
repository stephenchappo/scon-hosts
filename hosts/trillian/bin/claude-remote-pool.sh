#!/usr/bin/env bash
# Keeps POOL_SIZE remote-control-enabled Claude Code background agents
# running in TARGET_DIR. Run periodically (systemd timer) — idempotent,
# only tops up the pool when a session has exited (e.g. user typed `exit`
# in a remote-controlled session).
set -euo pipefail

TARGET_DIR="/home/scon/work"
POOL_SIZE=3
CLAUDE_BIN="/home/scon/.local/bin/claude"
LOG="/home/scon/logs/claude-remote-pool.log"

mkdir -p "$(dirname "$LOG")"

active=$("$CLAUDE_BIN" agents --json --cwd "$TARGET_DIR" 2>>"$LOG" | jq '[.[] | select(.kind == "background")] | length')
active=${active:-0}

need=$((POOL_SIZE - active))

if [ "$need" -gt 0 ]; then
  echo "$(date -Iseconds) active=$active need=$need — spinning up $need session(s)" >> "$LOG"
  cd "$TARGET_DIR"
  for _ in $(seq 1 "$need"); do
    "$CLAUDE_BIN" --bg --remote-control --permission-mode bypassPermissions >> "$LOG" 2>&1
  done
fi
