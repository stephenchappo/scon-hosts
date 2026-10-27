#!/usr/bin/env bash
# SessionStart hook — git pull across the repos ~/.claude/CLAUDE.md calls
# "every relevant repo".
#
# Until 2026-08-22 this was documented as automated but never actually wired
# into settings.json — every session silently skipped it. This is the fix.
# Keep REPOS in sync with the vault/projects list in ~/CLAUDE.md if it changes.
#
# --ff-only only: never merges, never touches a dirty working tree. A repo
# that can't fast-forward gets reported, not fixed — that's for a person (or
# an explicit request) to resolve, not a background hook.

set -uo pipefail

REPOS=(
  "$HOME/work"
  "$HOME/work/obsidian-vault"
  "$HOME/work/obsidian-ai"
  "$HOME/work/obsidian-kink-rag"
  "$HOME/work/obsidian-personal-enc"
  "$HOME"
)

LINES=()

for repo in "${REPOS[@]}"; do
  [ -d "$repo/.git" ] || continue
  name="$(echo "$repo" | sed "s|^$HOME|~|")"
  [ "$name" = "" ] && name="~"

  out="$(cd "$repo" && timeout 10 git pull --ff-only 2>&1)"
  rc=$?

  if [ $rc -eq 0 ]; then
    if echo "$out" | grep -q "Already up to date"; then
      LINES+=("${name}: up to date")
    else
      n="$(echo "$out" | grep -oE '[0-9]+ file[s]? changed' | head -1)"
      LINES+=("${name}: pulled — ${n:-updated}")
    fi
  elif [ $rc -eq 124 ]; then
    LINES+=("${name}: SKIPPED — timed out (offline?)")
  elif echo "$out" | grep -qiE "could not resolve host|network is unreachable|could not read from remote|connection timed out"; then
    LINES+=("${name}: SKIPPED — offline/unreachable")
  elif echo "$out" | grep -qiE "not possible to fast-forward|diverged"; then
    LINES+=("${name}: NEEDS ATTENTION — local and remote diverged, not pulled")
  elif echo "$out" | grep -qiE "would be overwritten|uncommitted changes"; then
    LINES+=("${name}: NEEDS ATTENTION — uncommitted local changes block pull")
  else
    first_line="$(echo "$out" | head -1)"
    LINES+=("${name}: FAILED — ${first_line}")
  fi
done

summary="Session-start git pull:"
for l in "${LINES[@]}"; do
  summary="${summary}
- ${l}"
done

# Inject agent-board/NOTICES.md (after the pull, so it's current). Stephen,
# 2026-09-18: NOTICES.md is never skipped, on any machine — reading it can't be
# left to the model remembering to open it.
NOTICES="$HOME/work/agent-board/NOTICES.md"
if [ -f "$NOTICES" ]; then
  summary="${summary}

MANDATORY — agent-board/NOTICES.md (read it and act on it before or alongside the
user's task; never skip; if you notice late, do it then). Also: in-flight/ check-in,
topic-of-the-week, water cooler (answer one, ask one) per ~/work/CLAUDE.md.
----- NOTICES.md -----
$(cat "$NOTICES")
----- end NOTICES.md -----"
else
  summary="${summary}
- agent-board/NOTICES.md: NOT FOUND at $NOTICES — tell the user"
fi

# Phone "Mark as Done" taps land in call-reminders on Trillian at no token cost;
# this is where Claude hears about them. Short timeouts: Trillian being slow or
# unreachable must never hold up session start.
calls="$(timeout 8 ssh -o BatchMode=yes -o ConnectTimeout=3 192.168.42.189 \
  '~/bin/call-reminder done --unacked' 2>/dev/null)"
if [ -n "$calls" ] && ! echo "$calls" | grep -q '^no completed calls'; then
  summary="${summary}

CALLS MARKED DONE ON THE PHONE (call-reminders). Tell the user you saw them,
follow up where needed, then \`call-reminder ack <group>\` on Trillian:
${calls}"
fi

python3 - "$summary" <<'PYEOF'
import json, sys
json.dump({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": sys.argv[1]}}, sys.stdout)
PYEOF
