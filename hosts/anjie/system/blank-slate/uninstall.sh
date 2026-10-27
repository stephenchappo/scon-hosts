#!/usr/bin/env bash
# Remove the blank-slate container.
#
#   bash uninstall.sh            removes ~/bin/blank, KEEPS /srv/blank-slate
#   bash uninstall.sh --purge    also deletes /srv/blank-slate and every
#                                transcript in it (irreversible, prompts first)
set -euo pipefail

ROOT=/srv/blank-slate

rm -f "${HOME}/bin/blank"
echo "Removed ~/bin/blank"

if [[ "${1:-}" == "--purge" ]]; then
    echo
    echo "About to permanently delete ${ROOT}, including:"
    sudo du -sh "${ROOT}" 2>/dev/null || true
    find "${ROOT}/config/projects" -name '*.jsonl' 2>/dev/null | wc -l | xargs echo "  transcript files:"
    read -r -p "Type PURGE to confirm: " reply
    [[ "$reply" == "PURGE" ]] || { echo "Aborted; ${ROOT} left in place."; exit 1; }
    sudo rm -rf "${ROOT}"
    echo "Deleted ${ROOT}"
else
    echo "${ROOT} left in place (transcripts kept). Use --purge to delete it."
fi
