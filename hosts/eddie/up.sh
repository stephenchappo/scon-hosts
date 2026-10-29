#!/usr/bin/env bash
# Create or update the cloud node "eddie". Run on Trillian (it has the Tailscale API key).
#
#   ./up.sh plan     # show what would change; creates nothing
#   ./up.sh apply    # create/update it (costs money: $28.80/mo once the droplet exists)
#   ./up.sh destroy  # delete it (the weekly backups go with it)
#
# Needs: tofu on PATH; DIGITALOCEAN_TOKEN (the scoped "scon-cloud" token);
# ~/.config/tailscale/api.env with TS_API_KEY (same file _project-meta/tailscale/apply.sh uses).
# State lives in ~/.local/state/scon-cloud/, never in git.
set -euo pipefail

ACTION=${1:-plan}
HERE=$(cd "$(dirname "$0")" && pwd)
STATE_DIR=$HOME/.local/state/scon-cloud
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

case "$ACTION" in plan|apply|destroy) ;; *) echo "usage: $0 plan|apply|destroy" >&2; exit 2;; esac
: "${DIGITALOCEAN_TOKEN:?set DIGITALOCEAN_TOKEN to the scoped scon-cloud token}"
command -v tofu >/dev/null || { echo "tofu not found: https://opentofu.org/docs/intro/install/" >&2; exit 1; }

# A fresh single-use key for every run: pre-approved, tagged tag:cloud, gone in an hour.
# The droplet ignores user_data changes after creation, so a new key never rebuilds it.
mint_key() {
  # shellcheck source=/dev/null
  . "$HOME/.config/tailscale/api.env"
  curl -fsS -u "$TS_API_KEY:" -H 'Content-Type: application/json' \
    https://api.tailscale.com/api/v2/tailnet/-/keys \
    -d '{"capabilities":{"devices":{"create":{"reusable":false,"ephemeral":false,"preauthorized":true,"tags":["tag:cloud"]}}},"expirySeconds":3600,"description":"eddie first boot"}' \
    | jq -er .key
}

if [ "$ACTION" = destroy ]; then
  export TF_VAR_tailscale_auth_key=unused
else
  TF_VAR_tailscale_auth_key=$(mint_key)
  export TF_VAR_tailscale_auth_key
fi

cd "$HERE/tofu"
tofu init -input=false >/dev/null
tofu "$ACTION" -input=false -state="$STATE_DIR/terraform.tfstate"
