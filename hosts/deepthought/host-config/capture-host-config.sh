#!/usr/bin/env bash
# Deepthought host-configuration capture -> stephenchappo/deepthought-home
#
# Vault: [[70-Homelab/Operations & Runbooks/Backup & DR]] §4b, checklist A8.
#
# WHY THIS EXISTS
#   backup-deepthought.sh protects this machine's service *data*. Nothing
#   protected the *machine*. Everything that makes those services start, reach
#   the network, see the GPU or find Marvin — systemd units, UFW, crontab, a
#   handful of /etc files — lived only on the root filesystem. A reimage would
#   have restored the nightly dumps into a host that could not run them.
#
# DESIGN RULES — all three are load-bearing
#
#   1. NEVER COMMIT A SECRET. This repo is pushed to GitHub. Secret-bearing
#      files are recorded as NAMES AND LOCATIONS ONLY, in secrets-inventory.md;
#      their values belong in the §6 escrow. A scanner runs over the staged tree
#      before anything is committed, and a hit aborts the run with nothing
#      written. Deny-list first, scanner second — belt and braces, because the
#      cost of being wrong once is permanent.
#
#   2. REGENERATE, DON'T ACCUMULATE. Owned directories are rebuilt from scratch
#      each run, so a decommissioned unit *disappears from the tree* and shows up
#      as a deletion in the diff. This deliberately differs from the rule in
#      backup-deepthought.sh ("no delete-sync, ever") and the difference is
#      justified: that script's deletions are unrecoverable, these are one
#      `git show` away. Drift you cannot see is the failure mode here, not loss.
#
#   3. CAPTURE ONLY WHAT HAS NO HOME. Anything already owned by a repo with an
#      installer is NOT copied — it is drift-checked against that repo instead.
#      Two copies of the same file in two repos is how you get a third,
#      disagreeing version. Today that means the Sony ingest pipeline, which
#      `~/work/sony-camera-ingest` owns end to end.
#
# Runs daily from cron at 00:45 — after backup-deepthought.sh (00:15) so a
# failure in one is legible against the other.

set -uo pipefail

REPO="$HOME"
OUT="$HOME/host-config"
INGEST_REPO="$HOME/work/sony-camera-ingest"
# No timestamp is written into the generated files. The commit date already
# carries it, and embedding it made every run produce a diff — which buries
# the real signal (a changed unit, a vanished service) in daily noise. A day
# with no commit now genuinely means the host did not change.
LOG="$HOME/logs/capture-host-config.log"

# Directories this script fully owns and rebuilds each run (rule 2).
OWNED=(systemd etc bin models ufw cron manifests state)

mkdir -p "$HOME/logs"
exec 3>&2
exec >>"$LOG" 2>&1
log()  { echo "$(date -Is) [capture-host-config] $*"; }
die()  { log "ABORT: $*"; echo "capture-host-config ABORT: $*" >&3; exit 1; }

log "=== start ==="

# ------------------------------------------------------------- preflight ----
[ "$(hostname)" = "deepthought" ] \
    || die "this script encodes deepthought's layout; refusing to run on $(hostname)"
[ -d "$REPO/.git" ] || die "$REPO is not a git repo"
git -C "$REPO" remote get-url origin 2>/dev/null | grep -q 'deepthought-home' \
    || die "$REPO/.git does not point at deepthought-home — refusing to write"
sudo -n true 2>/dev/null || die "passwordless sudo unavailable (needed for /etc and ufw)"

exec 9>/var/tmp/capture-host-config.lock
flock -n 9 || die "another run is already in progress"

STAGE="$(mktemp -d /var/tmp/capture-host-config.XXXXXX)" || die "cannot create staging dir"
trap '[ -n "${STAGE:-}" ] && rm -rf "$STAGE"' EXIT
log "staging in $STAGE"

# ---------------------------------------------------------- 1. systemd ------
# System units. The Sony ingest unit and the Marvin mount are deliberately
# ABSENT here — sony-camera-ingest owns them (rule 3); see the drift report.
mkdir -p "$STAGE/systemd/system" "$STAGE/systemd/user"
for u in ollama.service nvidia-persistence-mode.service; do
    sudo -n cp -a "/etc/systemd/system/$u" "$STAGE/systemd/system/" 2>/dev/null \
        || log "WARN: /etc/systemd/system/$u missing"
done
if [ -d /etc/systemd/system/ollama.service.d ]; then
    sudo -n cp -a /etc/systemd/system/ollama.service.d "$STAGE/systemd/system/"
fi

# User units. Copy real files only; a symlink here means the unit is already
# owned by a project repo (gpu-mode), so we record the link target instead of
# duplicating its contents.
for f in "$HOME"/.config/systemd/user/*.service "$HOME"/.config/systemd/user/*.timer; do
    [ -e "$f" ] || continue
    if [ -L "$f" ]; then
        printf '%s -> %s\n' "$(basename "$f")" "$(readlink -f "$f")" \
            >> "$STAGE/systemd/user/SYMLINKED-UNITS.txt"
    else
        cp -a "$f" "$STAGE/systemd/user/"
    fi
done
for d in "$HOME"/.config/systemd/user/*.d; do
    [ -d "$d" ] || continue
    cp -a "$d" "$STAGE/systemd/user/"
done
systemctl --user list-unit-files --state=enabled --no-legend \
    > "$STAGE/systemd/user/ENABLED.txt" 2>/dev/null
systemctl list-unit-files --state=enabled --no-legend \
    > "$STAGE/systemd/system/ENABLED.txt" 2>/dev/null

# ------------------------------------------------------------- 2. /etc ------
mkdir -p "$STAGE/etc/sudoers.d"
sudo -n cp -a /etc/fstab "$STAGE/etc/fstab"
sudo -n cp -a /etc/sudoers.d/scon-ollama "$STAGE/etc/sudoers.d/" 2>/dev/null
sudo -n chown -R "$(id -u):$(id -g)" "$STAGE/etc" "$STAGE/systemd"
# /etc/photo-ingest.env holds IMMICH_API_KEY — names only, never values.
sudo -n sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' /etc/photo-ingest.env \
    > "$STAGE/etc/photo-ingest.env.KEYS-ONLY" 2>/dev/null

# ------------------------------------------------- 3. ~/bin and modelfiles ---
mkdir -p "$STAGE/bin" "$STAGE/models"
for f in "$HOME"/bin/*; do
    [ -f "$f" ] && [ ! -L "$f" ] && cp -a "$f" "$STAGE/bin/"
done
find "$HOME/bin" -maxdepth 1 -type l -printf '%f -> %l\n' | sort \
    > "$STAGE/bin/SYMLINKED-SCRIPTS.txt"
cp -a "$HOME/models/modelfiles" "$STAGE/models/" 2>/dev/null
cp -a "$HOME/ai-server-setup.sh" "$STAGE/" 2>/dev/null

# -------------------------------------------------- 4. firewall and cron ----
mkdir -p "$STAGE/ufw" "$STAGE/cron"
sudo -n ufw status numbered > "$STAGE/ufw/rules.txt" 2>/dev/null \
    || log "WARN: could not read ufw status"
crontab -l > "$STAGE/cron/crontab.txt" 2>/dev/null \
    || log "WARN: no user crontab"

# -------------------------------------------------------- 5. manifests -----
# Tier 3 (§4b.4): ~338 GB that is deliberately NOT backed up. The recovery plan
# is "re-pull", so the list is the entire artefact.
mkdir -p "$STAGE/manifests"
ollama list > "$STAGE/manifests/ollama-models.txt" 2>/dev/null
(cd "$HOME/ComfyUI/custom_nodes" 2>/dev/null && for d in */; do
    [ -d "$d/.git" ] || continue
    printf '%-40s %s  %s\n' "${d%/}" \
        "$(git -C "$d" rev-parse --short HEAD 2>/dev/null)" \
        "$(git -C "$d" remote get-url origin 2>/dev/null)"
done) > "$STAGE/manifests/comfyui-custom-nodes.txt" 2>/dev/null
# Checkpoints: name + size + sha256. The hash is the point — several of these
# are Civitai-sourced and models do get delisted; a hash makes a substituted or
# missing file *detectable* rather than discovered mid-rebuild.
#
# Hashing 52 GB takes ~2 minutes, which is absurd to repeat nightly for files
# that change perhaps twice a year. Cached on (size, mtime): a checkpoint that
# has not been touched reuses its hash, and any change to either forces a
# rehash. The cache lives outside the repo — it is derived, not configuration.
HASH_CACHE="$HOME/.cache/capture-host-config/sdxl-hashes.tsv"
mkdir -p "$(dirname "$HASH_CACHE")"; touch "$HASH_CACHE"
(cd "$HOME/models/sdxl" 2>/dev/null && for f in *.safetensors; do
    [ -f "$f" ] || continue
    size="$(stat -c %s "$f")"; mtime="$(stat -c %Y "$f")"
    hash="$(awk -F'\t' -v f="$f" -v s="$size" -v m="$mtime" \
            '$1==f && $2==s && $3==m {print $4; exit}' "$HASH_CACHE")"
    if [ -z "$hash" ]; then
        hash="$(sha256sum "$f" | cut -d' ' -f1)"
        printf '%s\t%s\t%s\t%s\n' "$f" "$size" "$mtime" "$hash" >> "$HASH_CACHE"
        log "hashed $f (cache miss)"
    fi
    printf '%s  %s  %s\n' "$hash" "$size" "$f"
done) > "$STAGE/manifests/sdxl-checkpoints.txt" 2>/dev/null
docker volume ls --format '{{.Name}}' | sort > "$STAGE/manifests/docker-volumes.txt" 2>/dev/null
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | sort \
    > "$STAGE/manifests/docker-images.txt" 2>/dev/null

# ------------------------------------------------------------ 6. state ------
# Facts a rebuild needs that are not files.
mkdir -p "$STAGE/state"
{
    echo "# Host state — regenerated each run; see the commit date"
    echo
    echo "kernel:        $(uname -r)"
    echo "os:            $(. /etc/os-release && echo "$PRETTY_NAME")"
    # Assert, don't paste. A driver/library mismatch makes nvidia-smi fail in a
    # way that is easy to skim past in a status dump — but it means every CUDA
    # service on this host has silently fallen back to CPU. Found exactly that
    # on this script's first run, 2026-09-11.
    nvml="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>&1 | head -1)"
    krnl="$(sed -n 's/^NVRM version:.*Module *\([0-9.]*\).*/\1/p' /proc/driver/nvidia/version 2>/dev/null)"
    if printf '%s' "$nvml" | grep -qi 'mismatch\|failed'; then
        echo "nvidia:        *** MISMATCH — userspace vs kernel module ***"
        echo "                   nvidia-smi: $nvml"
        echo "                   kernel module loaded: ${krnl:-unknown}"
        echo "                   CUDA is unavailable; services are on CPU. Reboot to load the built module."
    else
        echo "nvidia driver: $nvml (kernel module ${krnl:-unknown})"
    fi
    echo "dkms:          $(dkms status 2>/dev/null | tr '\n' ';')"
    echo "ollama:        $(ollama --version 2>/dev/null | head -1)"
    echo "docker:        $(docker --version 2>/dev/null)"
    echo
    echo "# linger MUST be enabled or every user unit dies at logout"
    echo "linger(scon):  $(loginctl show-user scon --property=Linger 2>/dev/null)"
    echo
    echo "# mounts — absent means NOT MOUNTED, which is the F3 condition"
    for m in /marvin /mnt/marvin/photos /mnt/media_drive; do
        findmnt -no SOURCE,TARGET,FSTYPE "$m" 2>/dev/null || echo "(not mounted)  $m"
    done
} > "$STAGE/state/host.txt"

# ------------------------------------------------------ 7. drift report -----
# Rule 3. sony-camera-ingest owns the ingest pipeline; we check it matches
# rather than keeping a second copy that can disagree.
{
    echo "# Drift: deployed vs ~/work/sony-camera-ingest"
    echo "#"
    echo "# This repo does NOT carry these files. If a line below says DIFF or"
    echo "# ABSENT-IN-REPO, the deployed host has drifted from its own installer"
    echo "# and a reimage would restore the WRONG version. Fix it in that repo."
    echo
    ok=1
    for pair in \
        "systemd/mnt-marvin-photos.mount:/etc/systemd/system/mnt-marvin-photos.mount" \
        "systemd/sony-a7iv-ingest@.service:/etc/systemd/system/sony-a7iv-ingest@.service" \
        "udev/90-sony-a7iv-ingest.rules:/etc/udev/rules.d/90-sony-a7iv-ingest.rules"; do
        r="$INGEST_REPO/${pair%%:*}"; d="${pair##*:}"
        if sudo -n diff -q "$r" "$d" >/dev/null 2>&1; then echo "SAME            ${d}"
        else echo "DIFF            ${d}"; ok=0; fi
    done
    for f in /opt/photo-ingest/*; do
        [ -f "$f" ] || continue
        b="$(basename "$f")"
        r="$(find "$INGEST_REPO" -name "$b" -not -path '*/.git/*' 2>/dev/null | head -1)"
        if [ -z "$r" ]; then echo "ABSENT-IN-REPO  $f"; ok=0
        elif sudo -n diff -q "$r" "$f" >/dev/null 2>&1; then echo "SAME            $f"
        else echo "DIFF            $f"; ok=0; fi
    done
    echo
    [ "$ok" = 1 ] && echo "# clean" || echo "# DRIFTED — see above"
} > "$STAGE/state/ingest-drift.txt" 2>/dev/null

# ------------------------------------------------- 8. secrets inventory -----
# Names and locations only. This file is the bridge to §6 escrow: it tells a
# rebuild exactly what it must go and fetch, without being the thing that leaks.
{
    echo "# Secrets this host needs, and where they live"
    echo "#"
    echo "# VALUES ARE NEVER RECORDED HERE. This file is pushed to GitHub."
    echo "# It exists so a rebuild knows what to retrieve from escrow"
    echo "# ([[Break Glass - Digital Life Recovery]], plan §6)."
    echo
    echo "## Layer A — unrecoverable if lost"
    printf -- '- %-46s %s\n' "~/.age/key.txt" "decrypts _project-meta/secrets/*.age"
    printf -- '- %-46s %s\n' "n8n N8N_ENCRYPTION_KEY" "captured inside the nightly n8n backup tarball"
    echo
    echo "## Layer B — reissuable from account access"
    printf -- '- %-46s %s\n' "~/.ssh/id_ed25519" "machine -> GitHub; regenerate on rebuild, do not hunt for it"
    printf -- '- %-46s %s\n' "~/.claude/.credentials.json" "re-auth via claude login"
    echo
    echo "## Service .env files — present on disk, gitignored by design"
    for f in $(find /srv/docker/deepthought -maxdepth 2 -name '.env' | sort); do
        printf -- '- %-46s %s\n' "$f" "$(grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' "$f" 2>/dev/null || echo '?') keys"
    done
    printf -- '- %-46s %s\n' "/etc/photo-ingest.env" "keys listed in etc/photo-ingest.env.KEYS-ONLY"
    echo
    echo "## Absent on this host (noted so its absence is not mistaken for loss)"
    printf -- '- %-46s %s\n' "~/.config/gocryptfs/personal-vault.pass" "provisioned manually; personal vault not mounted here"
} > "$STAGE/secrets-inventory.md"

# ------------------------------------------------------- 9. SECRET SCAN -----
# Rule 1, second line of defence. Runs over the STAGED tree — nothing has
# touched the repo yet, so an abort here leaves no trace.
SCAN_HITS="$(grep -rInE \
    -e '(BEGIN [A-Z ]*PRIVATE KEY)' \
    -e '(api[_-]?key|secret|password|passwd|token|credential)[[:space:]]*[=:][[:space:]]*[^[:space:]]{8,}' \
    -e '\b(sk-|ghp_|github_pat_|xox[baprs]-|AKIA|AgeSecretKey)' \
    "$STAGE" 2>/dev/null \
    | grep -v '^.*secrets-inventory.md' \
    | grep -v 'KEYS-ONLY' )"
if [ -n "$SCAN_HITS" ]; then
    log "SECRET SCAN TRIPPED — nothing written:"
    printf '%s\n' "$SCAN_HITS" | head -20
    die "possible secret in staged tree; nothing was committed (see $LOG)"
fi
log "secret scan clean"

# ------------------------------------------------------------ 10. swap ------
for d in "${OWNED[@]}"; do rm -rf "${OUT:?}/$d"; done
rm -f "$OUT/ai-server-setup.sh" "$OUT/secrets-inventory.md"
cp -a "$STAGE"/. "$OUT"/
chmod -R go-w "$OUT" 2>/dev/null || true

# ----------------------------------------------------------- 11. commit -----
cd "$REPO" || die "cannot cd $REPO"
git add -A host-config >/dev/null 2>&1
if git diff --cached --quiet -- host-config; then
    log "no change"
    log "=== OK (nothing to commit) ==="
    exit 0
fi
SUMMARY="$(git diff --cached --numstat -- host-config | wc -l) file(s)"
if ! git commit -q -m "host-config: capture $(date +%F) — $SUMMARY" -- host-config; then
    die "commit failed"
fi
if git push -q 2>/dev/null; then
    log "committed and pushed — $SUMMARY"
else
    log "committed locally; PUSH FAILED — $SUMMARY"
    echo "capture-host-config: push failed, commit is local only" >&3
fi

grep -q 'DRIFTED' "$OUT/state/ingest-drift.txt" 2>/dev/null \
    && log "NOTE: ingest pipeline has drifted from sony-camera-ingest"

log "=== OK ==="
exit 0
