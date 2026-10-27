#!/usr/bin/env bash
set -euo pipefail
~/work/debt-tracker/.venv/bin/python3 ~/work/debt-tracker/sync_to_vault.py "$@"
