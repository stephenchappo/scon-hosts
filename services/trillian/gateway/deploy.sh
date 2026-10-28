#!/usr/bin/env bash
# Deploy the gateway on Trillian. STAGED: refuses to start anything until the
# go-live marker exists (created by hand after the D9 review and Scon's card).
#
#   deploy.sh --check      validate + test the candidate tables (origin/main of scon-system); starts nothing
#   deploy.sh              check, then switch to the candidate; roll back on any failure after that
#   deploy.sh --rollback   switch back to the last-known-good release
#
# A release is one scon-system commit (the tables) plus one scon-hosts commit (the code, as an
# image tagged by that commit), recorded in $BASE/releases/<name>.env. Rollback restores both.
# Policy changes arrive only as merged commits to scon-system main (workers propose by PR;
# D7). A candidate that fails the policy check or the tests is never switched to.
set -euo pipefail
shopt -s inherit_errexit
set +x
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=${GATEWAY_HOME:-$HOME/.local/share/scon-gateway}
LIVE_MARKER=${GATEWAY_LIVE_MARKER:-$HOME/.config/scon-gateway/LIVE}
SYSTEM_REMOTE=${SYSTEM_REMOTE:-git@github.com:stephenchappo/scon-system.git}
export GATEWAY_DATA_DIR=${GATEWAY_DATA_DIR:-$HOME/.local/state/scon-gateway}
export GATEWAY_RESTRICTED_LOG_DIR=${GATEWAY_RESTRICTED_LOG_DIR:-$HOME/work/restricted/kink-courses/logs/gateway}
export GATEWAY_UID=$(id -u) GATEWAY_GID=$(id -g)
mode=${1:-deploy}

mkdir -p "$BASE/releases" "$GATEWAY_DATA_DIR/state" "$GATEWAY_DATA_DIR/log"
exec 9>"$BASE/deploy.lock"
flock -n 9 || { echo "another deploy is running"; exit 1; }
[ -d "$BASE/system/.git" ] || git clone -q "$SYSTEM_REMOTE" "$BASE/system"
git -C "$BASE/system" fetch -q origin main

checkout() {  # checkout <name> <sha>: a detached worktree per pinned commit
  rm -rf "$BASE/$1"; git -C "$BASE/system" worktree prune
  git -C "$BASE/system" worktree add -q --detach "$BASE/$1" "$2"
}

check() {  # check <dir>: policy check + full test suite; prints the policy digest
  [ -s "$1/benchmark/canaries.json" ] || { echo "no canary registry in $1" >&2; return 1; }
  docker build -q --target test -t scon-gateway:test "$HERE" >/dev/null || return 1
  docker run --rm --network none -v "$1/gateway:/tables:ro" scon-gateway:test >&2 || return 1
  docker run --rm --network none -v "$1/gateway:/tables:ro" scon-gateway:test python3 -m app.policy /tables \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["digest"])'
}

preflight() {  # state and restricted log must be writable before anything switches
  for d in "$GATEWAY_DATA_DIR/state" "$GATEWAY_DATA_DIR/log" "$GATEWAY_RESTRICTED_LOG_DIR"; do
    mkdir -p "$d" && touch "$d/.w" && rm -f "$d/.w" || { echo "not writable: $d"; return 1; }
  done
}

wt() { echo "$BASE/wt-$1"; }  # one worktree per deployed system commit; old ones are pruned after success

start() {  # start <release-file>: its own tables worktree, its own image, then health against its digest
  local SYSTEM_SHA HOSTS_SHA IMAGE DIGEST
  . "$1"
  [ -d "$(wt "$SYSTEM_SHA")" ] || checkout "wt-$SYSTEM_SHA" "$SYSTEM_SHA" || return 1
  docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "image $IMAGE is gone"; return 1; }
  export GATEWAY_SYSTEM_CHECKOUT=$(wt "$SYSTEM_SHA") GATEWAY_IMAGE=$IMAGE GATEWAY_RELEASE=$(basename "$1" .env)
  python3 "$HERE/gen_override.py" "$GATEWAY_SYSTEM_CHECKOUT/gateway" > "$HERE/compose.override.yaml.new" || return 1
  mv "$HERE/compose.override.yaml.new" "$HERE/compose.override.yaml" || return 1
  (cd "$HERE" && "$HERE/../../../bin/bws-run" gateway -- docker compose up -d --no-build --force-recreate) || return 1
  sleep 5
  "$HERE/health.sh" "$DIGEST" "$GATEWAY_RELEASE"
}

# The code half of a release is the committed scon-hosts tree, never uncommitted edits.
[ -z "$(git -C "$HERE" status --porcelain -- .)" ] || { echo "uncommitted changes in $HERE; commit first"; exit 1; }
HOSTS_SHA=$(git -C "$HERE" rev-parse HEAD)
sha=$(git -C "$BASE/system" rev-parse origin/main)
case "$mode" in
  --check)
    checkout candidate "$sha"; digest=$(check "$BASE/candidate"); echo "candidate $sha passes (policy $digest)"; exit 0 ;;
  --rollback)
    [ -f "$LIVE_MARKER" ] || { echo "gateway is staged, not live ($LIVE_MARKER missing)"; exit 1; }
    [ -f "$BASE/lkg" ] || { echo "no last-known-good release recorded"; exit 1; }
    rel=$(cat "$BASE/lkg")
    start "$BASE/releases/$rel.env" && { echo "$rel" > "$BASE/current"; echo "rolled back to $rel"; exit 0; }
    echo "ROLLBACK FAILED: gateway is down (fails closed)"; exit 1 ;;
  *)
    [ -f "$LIVE_MARKER" ] || { echo "gateway is staged, not live ($LIVE_MARKER missing). Use --check."; exit 1; } ;;
esac

checkout candidate "$sha"; digest=$(check "$BASE/candidate"); preflight
image="scon-gateway:${HOSTS_SHA:0:12}"
docker build -q --target service -t "$image" "$HERE" >/dev/null
rel="${sha:0:12}-${HOSTS_SHA:0:12}"
printf 'SYSTEM_SHA=%s\nHOSTS_SHA=%s\nIMAGE=%s\nDIGEST=%s\n' "$sha" "$HOSTS_SHA" "$image" "$digest" \
  > "$BASE/releases/$rel.env"
prev=$(cat "$BASE/current" 2>/dev/null || true)
# From here every failure restores the previous release, whose worktree and image are kept until the new one is healthy.
set +e
start "$BASE/releases/$rel.env"; ok=$?
set -e
if [ $ok = 0 ]; then
  [ -n "$prev" ] && [ "$prev" != "$rel" ] && echo "$prev" > "$BASE/lkg"
  echo "$rel" > "$BASE/current"
  keep=$(cat "$BASE/lkg" 2>/dev/null || true)
  keep_sys=$( [ -n "$keep" ] && . "$BASE/releases/$keep.env" && echo "$SYSTEM_SHA" || true)
  for d in "$BASE"/wt-*; do
    s=${d##*/wt-}; [ "$s" = "$sha" ] || [ "$s" = "$keep_sys" ] || rm -rf "$d"
  done
  git -C "$BASE/system" worktree prune
  echo "deployed $rel"
  exit 0
fi
echo "switch to $rel failed"
if [ -n "$prev" ] && [ "$prev" != "$rel" ]; then
  start "$BASE/releases/$prev.env" && echo "restored $prev" || echo "RESTORE FAILED: gateway is down (fails closed)"
fi
exit 1
