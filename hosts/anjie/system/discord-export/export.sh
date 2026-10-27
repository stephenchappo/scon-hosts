#!/usr/bin/env bash
# Export Discord DMs into the personal vault with DiscordChatExporter.
#
#   ~/system/discord-export/export.sh list            # show DM channels + ids
#   ~/system/discord-export/export.sh text <id>...    # JSON only, no media  (fast)
#   ~/system/discord-export/export.sh full <id>...    # JSON + HTML + media  (slow)
#   ~/system/discord-export/export.sh alltext         # every DM, text only
#
# Do the text pass first. Media is the bottleneck by an order of magnitude — a
# single busy DM ran to 817 MB and 11% in 15 minutes — and the record needs the
# words, not the attachments.
#
# Token is read from ~/.config/discord-export/token (mode 0600, never an argument
# — arguments show up in ps and in shell history).
#
# Output is Tier-1 personal data and lands in the gocryptfs vault only.
set -euo pipefail

DCE=~/.local/opt/discord-chat-exporter/DiscordChatExporter.Cli
TOKEN_FILE=~/.config/discord-export/token
OUT=~/work/obsidian-personal/60-Personal\ Information/Signal\ Archive/_archive-source/discord-export-$(date +%Y%m%d)

[[ -x "$DCE" ]] || { echo "DiscordChatExporter not at $DCE"; exit 1; }
[[ -f "$TOKEN_FILE" ]] || { echo "no token at $TOKEN_FILE — see README.md"; exit 1; }
if [[ "$(stat -c %a "$TOKEN_FILE")" != "600" ]]; then
    echo "tightening permissions on $TOKEN_FILE"; chmod 600 "$TOKEN_FILE"
fi
DISCORD_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
export DISCORD_TOKEN
[[ -n "$DISCORD_TOKEN" ]] || { echo "token file is empty"; exit 1; }

case "${1:-}" in
  list)
    "$DCE" dm --token "$DISCORD_TOKEN"
    ;;
  text|full|alltext)
    mode="$1"; shift
    mkdir -p "$OUT/json"
    # --parallel 1 and DCE's own rate limiting are deliberate: hammering the API
    # is what actually gets an account flagged. This is slow on purpose.
    common=(--token "$DISCORD_TOKEN" --parallel 1 --markdown false)
    [[ "$mode" == "full" ]] && common+=(--media --reuse-media)

    if [[ "$mode" == "alltext" ]]; then
        sel=(exportdm)
    else
        [[ $# -gt 0 ]] || { echo "give at least one channel id"; exit 1; }
        sel=(export --channel "$@")
    fi

    echo "--- JSON ---"
    "$DCE" "${sel[@]}" "${common[@]}" --format Json --output "$OUT/json/"
    if [[ "$mode" == "full" ]]; then
        mkdir -p "$OUT/html"
        echo "--- HTML ---"
        "$DCE" "${sel[@]}" "${common[@]}" --format HtmlDark --output "$OUT/html/"
    fi
    echo
    echo "written to $OUT"
    ;;
  *)
    sed -n '2,12p' "$0"; exit 1
    ;;
esac
