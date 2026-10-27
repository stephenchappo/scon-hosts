# host-config — what this machine looked like

Captured automatically by `capture-host-config.sh`, daily at 00:45.
Plan: **[[Homelab - Backup & DR Strategy (v0)]] §4b** (Tier 2b), checklist A8.

**This directory is not a backup of data.** Deepthought's service data goes to
Marvin nightly via `/srv/docker/scripts/backup-deepthought.sh`. This is the
other half: the host configuration that makes that data *runnable*. Restoring
one without the other gets you either a machine with no state, or state with no
machine.

## What is here

| Path | Contents |
|---|---|
| `systemd/system/` | `ollama.service` + its drop-ins, `nvidia-persistence-mode.service`, enabled-unit list |
| `systemd/user/` | 8 user units + drop-in directories, enabled list, and the symlinked-unit map |
| `etc/` | `fstab`, `sudoers.d/scon-ollama`, and the **key names only** of `photo-ingest.env` |
| `bin/` | the real scripts in `~/bin`, plus a map of the symlinks into project repos |
| `models/modelfiles/` | `chat.Modelfile`, `big.Modelfile` — these *are* the Ollama task aliases |
| `ufw/rules.txt` | the firewall, verbatim |
| `cron/crontab.txt` | including the line that runs the nightly backup |
| `manifests/` | Tier 3 re-pull lists: Ollama models, ComfyUI nodes + SHAs, SDXL checkpoint hashes, Docker volumes and images |
| `state/host.txt` | kernel, driver, linger, mounts |
| `state/ingest-drift.txt` | deployed-vs-repo check for the Sony ingest pipeline |
| `secrets-inventory.md` | what secrets exist and where — **never their values** |

## What is deliberately NOT here

- **Secret values.** Anything sensitive is a name and a location, pointing at
  [[Break Glass - Digital Life Recovery]]. This repo is pushed to GitHub.
- **The Sony ingest pipeline.** `~/work/sony-camera-ingest` owns it, with a
  working `install.sh`. Keeping a second copy here is how you end up with a
  third, disagreeing version — so this directory *drift-checks* it instead.
  Read `state/ingest-drift.txt`; if it says `DRIFTED`, fix that repo, not this one.
- **~338 GB of models and ComfyUI nodes.** Tier 3 by decision. The manifests are
  the whole recovery plan: re-pull, don't restore.
- **Anything from `/srv/docker`.** That is its own repo, `docker-configs`.

## Restoring

The ordered procedure is **§9 "Deepthought dies"** in the plan. Read that, not
this file — it sequences these artefacts against escrow and the data restore,
and the order is the part that matters.

Two things that will bite regardless:

1. **`loginctl enable-linger scon`**, or every user unit dies the moment your
   SSH session ends. The host looks perfectly healthy right up until you log out.
2. **Verify from Trillian, not locally.** Several UFW rules exist only to be
   *reached from* Trillian. A locally-green Deepthought can still be invisible
   to alerting — that exact state went unnoticed for ten days to 2026-08-23.

## Reading the diffs

The daily commit is the point, not just the contents. Because the capture
regenerates each owned directory from scratch, a decommissioned unit shows up as
a **deletion** and a retuned drop-in shows up as a **modification**. Host drift
becomes reviewable history. The stale service entries and phantom Ollama models
found by hand on 2026-08-13 would have appeared here as a diff on the day.

An empty day means nothing changed, and the script commits nothing.
