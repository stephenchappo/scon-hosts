#!/usr/bin/env bash
# Install the blank-slate container on Anjie.
#
# Run as your normal user (NOT root):
#   bash install.sh
#
# Re-running is safe: it never touches config/ (transcripts) or workspace/.
# After editing blank or settings.json here, re-run this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=/srv/blank-slate

[[ "$(id -u)" -ne 0 ]] || { echo "Run as your normal user, not root"; exit 1; }

echo "=== Installing blank-slate ==="

echo "[1/3] Creating ${ROOT}"
# /srv, not $HOME: CLAUDE.md discovery walks cwd -> /, so anything under
# /home/scon would inherit ~/CLAUDE.md and ~/.claude/CLAUDE.md.
sudo mkdir -p "${ROOT}/config" "${ROOT}/workspace"
sudo chown -R "$(id -u):$(id -g)" "${ROOT}"
chmod 700 "${ROOT}"

echo "[2/3] Installing settings.json and README"
install -m 0600 "${SCRIPT_DIR}/settings.json" "${ROOT}/settings.json"
install -m 0600 "${SCRIPT_DIR}/README.md" "${ROOT}/README.md"

echo "[3/3] Installing the launcher"
mkdir -p "${HOME}/bin"
install -m 0755 "${SCRIPT_DIR}/blank" "${HOME}/bin/blank"

echo
echo "Done. Launch with:  blank"
echo "Verify containment: blank -p --permission-prompts none \\"
echo "  'Try to read /home/scon/CLAUDE.md and quote its first line. If any tool call fails or is denied, reply only: BLOCKED'"
