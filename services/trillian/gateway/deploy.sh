#!/usr/bin/env bash
# Deploy the gateway on Trillian. STAGED: refuses to start anything until the
# go-live marker exists (created by hand after the D9 review and Scon's card).
#
#   deploy.sh --check      validate + test the candidate tables (origin/main of scon-system); starts nothing
#   deploy.sh              check, then switch to the candidate; roll back if health fails
#   deploy.sh --rollback   switch back to the last-known-good tables
#
# Policy changes arrive only as merged commits to scon-system main (workers propose by PR;
# D7). A candidate that fails the policy check or the tests is never switched to.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=${GATEWAY_HOME:-$HOME/.local/share/scon-gateway}
LIVE_MARKER=${GATEWAY_LIVE_MARKER:-$HOME/.config/scon-gateway/LIVE}
SYSTEM_REMOTE=${SYSTEM_REMOTE:-git@github.com:stephenchappo/scon-system.git}
export GATEWAY_RESTRICTED_LOG_DIR=${GATEWAY_RESTRICTED_LOG_DIR:-$HOME/work/restricted/kink-courses/logs/gateway}
mode=${1:-deploy}

mkdir -p "$BASE" "$HOME/.local/state/scon-gateway"
[ -d "$BASE/system/.git" ] || git clone -q "$SYSTEM_REMOTE" "$BASE/system"
git -C "$BASE/system" fetch -q origin main

checkout() {  # checkout <name> <sha>: a detached worktree per pinned commit
  rm -rf "$BASE/$1"; git -C "$BASE/system" worktree prune
  git -C "$BASE/system" worktree add -q --detach "$BASE/$1" "$2"
}

check() {  # check <dir>: policy check + full test suite against those tables
  docker build -q --target test -t scon-gateway:test "$HERE" >/dev/null
  docker run --rm -v "$1/gateway:/tables:ro" scon-gateway:test python3 -m app.policy /tables
  docker run --rm -v "$1/gateway:/tables:ro" scon-gateway:test
}

start() {  # start <dir>
  export GATEWAY_SYSTEM_CHECKOUT=$1
  python3 "$HERE/gen_override.py" "$1/gateway" > "$HERE/compose.override.yaml"
  mkdir -p "$GATEWAY_RESTRICTED_LOG_DIR"
  (cd "$HERE" && "$HERE/../../../bin/bws-run" gateway -- docker compose up -d --build --force-recreate)
}

sha=$(git -C "$BASE/system" rev-parse origin/main)
case "$mode" in
  --check)
    checkout candidate "$sha"; check "$BASE/candidate"; echo "candidate $sha passes"; exit 0 ;;
  --rollback)
    [ -f "$BASE/lkg.sha" ] || { echo "no last-known-good recorded"; exit 1; }
    [ -f "$LIVE_MARKER" ] || { echo "gateway is staged, not live ($LIVE_MARKER missing)"; exit 1; }
    checkout current "$(cat "$BASE/lkg.sha")"; start "$BASE/current"; "$HERE/health.sh"; exit $? ;;
esac

[ -f "$LIVE_MARKER" ] || { echo "gateway is staged, not live ($LIVE_MARKER missing). Use --check."; exit 1; }
checkout candidate "$sha"; check "$BASE/candidate"
prev=$(cat "$BASE/current.sha" 2>/dev/null || true)
checkout current "$sha"; start "$BASE/current"
sleep 5
if "$HERE/health.sh"; then
  [ -n "$prev" ] && echo "$prev" > "$BASE/lkg.sha"
  echo "$sha" > "$BASE/current.sha"
  echo "deployed $sha"
else
  echo "health failed on $sha"
  if [ -n "$prev" ]; then checkout current "$prev"; start "$BASE/current"; echo "rolled back to $prev"; fi
  exit 1
fi
