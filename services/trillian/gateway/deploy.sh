#!/usr/bin/env bash
# Deploy the gateway on Trillian. STAGED: refuses to start anything until the
# go-live marker exists (created by hand after the D9 review and Scon's card).
#
#   deploy.sh --check      validate + test the candidate tables (origin/main of scon-system); starts nothing
#   deploy.sh              check, then switch to the candidate; roll back on any failure after that
#   deploy.sh --rollback   switch back to the last-known-good tables
#
# Policy changes arrive only as merged commits to scon-system main (workers propose by PR;
# D7). A candidate that fails the policy check or the tests is never switched to.
set -euo pipefail
set +x
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=${GATEWAY_HOME:-$HOME/.local/share/scon-gateway}
LIVE_MARKER=${GATEWAY_LIVE_MARKER:-$HOME/.config/scon-gateway/LIVE}
SYSTEM_REMOTE=${SYSTEM_REMOTE:-git@github.com:stephenchappo/scon-system.git}
export GATEWAY_DATA_DIR=${GATEWAY_DATA_DIR:-$HOME/.local/state/scon-gateway}
export GATEWAY_RESTRICTED_LOG_DIR=${GATEWAY_RESTRICTED_LOG_DIR:-$HOME/work/restricted/kink-courses/logs/gateway}
export GATEWAY_UID=$(id -u) GATEWAY_GID=$(id -g)
mode=${1:-deploy}

mkdir -p "$BASE" "$GATEWAY_DATA_DIR/state" "$GATEWAY_DATA_DIR/log"
[ -d "$BASE/system/.git" ] || git clone -q "$SYSTEM_REMOTE" "$BASE/system"
git -C "$BASE/system" fetch -q origin main

checkout() {  # checkout <name> <sha>: a detached worktree per pinned commit
  rm -rf "$BASE/$1"; git -C "$BASE/system" worktree prune
  git -C "$BASE/system" worktree add -q --detach "$BASE/$1" "$2"
}

check() {  # check <dir>: policy check + full test suite against those tables and their canaries
  [ -s "$1/benchmark/canaries.json" ] || { echo "no canary registry in $1"; return 1; }
  docker build -q --target test -t scon-gateway:test "$HERE" >/dev/null
  docker run --rm --network none -v "$1/gateway:/tables:ro" scon-gateway:test python3 -m app.policy /tables
  docker run --rm --network none -v "$1/gateway:/tables:ro" scon-gateway:test
}

preflight() {  # state and restricted log must be writable before anything switches
  for d in "$GATEWAY_DATA_DIR/state" "$GATEWAY_DATA_DIR/log" "$GATEWAY_RESTRICTED_LOG_DIR"; do
    mkdir -p "$d" && touch "$d/.w" && rm -f "$d/.w" || { echo "not writable: $d"; return 1; }
  done
}

start() {  # start <dir>
  export GATEWAY_SYSTEM_CHECKOUT=$1
  python3 "$HERE/gen_override.py" "$1/gateway" > "$HERE/compose.override.yaml"
  (cd "$HERE" && "$HERE/../../../bin/bws-run" gateway -- docker compose up -d --build --force-recreate)
}

wt() { echo "$BASE/wt-$1"; }  # one worktree per deployed commit; old ones are pruned after success

switch_to() {  # switch_to <sha>: start it from its own worktree and check health
  [ -d "$(wt "$1")" ] || checkout "wt-$1" "$1"
  start "$(wt "$1")" && sleep 5 && "$HERE/health.sh"
}

sha=$(git -C "$BASE/system" rev-parse origin/main)
case "$mode" in
  --check)
    checkout candidate "$sha"; check "$BASE/candidate"; echo "candidate $sha passes"; exit 0 ;;
  --rollback)
    [ -f "$LIVE_MARKER" ] || { echo "gateway is staged, not live ($LIVE_MARKER missing)"; exit 1; }
    [ -f "$BASE/lkg.sha" ] || { echo "no last-known-good recorded"; exit 1; }
    sha=$(cat "$BASE/lkg.sha") ;;
  *)
    [ -f "$LIVE_MARKER" ] || { echo "gateway is staged, not live ($LIVE_MARKER missing). Use --check."; exit 1; } ;;
esac

checkout candidate "$sha"; check "$BASE/candidate"; preflight
prev=$(cat "$BASE/current.sha" 2>/dev/null || true)
# From here every failure restores the previous commit, whose worktree is kept until the new one is healthy.
set +e
switch_to "$sha"; ok=$?
set -e
if [ $ok = 0 ]; then
  [ -n "$prev" ] && [ "$prev" != "$sha" ] && echo "$prev" > "$BASE/lkg.sha"
  echo "$sha" > "$BASE/current.sha"
  keep_lkg=$(cat "$BASE/lkg.sha" 2>/dev/null || true)
  for d in "$BASE"/wt-*; do
    s=${d##*/wt-}; [ "$s" = "$sha" ] || [ "$s" = "$keep_lkg" ] || rm -rf "$d"
  done
  git -C "$BASE/system" worktree prune
  echo "deployed $sha"
  exit 0
fi
echo "switch to $sha failed"
if [ -n "$prev" ] && [ "$prev" != "$sha" ]; then
  switch_to "$prev" && echo "restored $prev" || echo "RESTORE FAILED: gateway is down (fails closed)"
fi
exit 1
