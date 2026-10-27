#!/usr/bin/env bash
# Ensure the five "Remote N" tmux sessions exist, each running Claude Code with
# Remote Control enabled. Idempotent: existing sessions are left untouched, only
# missing ones are (re)created. Safe to run repeatedly and at boot.
set -uo pipefail

CLAUDE="$HOME/.local/bin/claude"
WORKDIR="$HOME/work"
COUNT=5

command -v tmux >/dev/null || { echo "tmux not found"; exit 1; }
[ -x "$CLAUDE" ] || { echo "claude not found at $CLAUDE"; exit 1; }

for i in $(seq 1 "$COUNT"); do
  name="Remote $i"
  if tmux has-session -t "$name" 2>/dev/null; then
    echo "$name: already running, left alone"
    continue
  fi
  # Pane runs a shell; Claude is a child, so quitting Claude drops to a prompt
  # instead of destroying the session.
  tmux new-session -d -s "$name" -c "$WORKDIR"
  tmux send-keys -t "$name" "$CLAUDE --remote-control \"$name\"" C-m
  echo "$name: created"
done
