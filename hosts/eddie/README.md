# eddie: the cloud node

A small DigitalOcean server that joins the tailnet as `tag:cloud`. It's a second place to run
jobs when Trillian or Deepthought is down, a home for jobs that belong outside the house, and a
lab for running a distributed system. Named after the Heart of Gold's shipboard computer.

Decided by Scon on 2026-10-29 (study: https://claude.ai/artifact/HahKt5dutyNxy8hr2z9EAe):
DigitalOcean `sfo3`, Basic `s-2vcpu-4gb` (2 vCPU, 4 GB, 80 GB) with weekly backups,
**$28.80/month** list price ($24 + $4.80), before tax.

## Rules

- **No Tier-1 or Restricted data here, ever.** Trillian is trusted for everything; a rented
  server isn't. A job that needs that data stays home.
- **No MAM, torrent or yt-dlp traffic.** That stays on the seedbox.
- **Disposable.** Everything about it is in this folder and the jobs registry. Rebuild rather
  than repair.
- **Tailnet only.** The only inbound port is Tailscale's UDP 41641. Admin is Tailscale SSH.
  It doesn't accept the home subnet route, and the tailnet policy lets it reach only Loki and
  Homepage at home (`_project-meta/tailscale/policy.hujson` in `projects`).

## Files

| File | What it is |
|---|---|
| `tofu/` | OpenTofu: the droplet, its weekly backup, the cloud firewall |
| `cloud-init.yaml` | First boot: user `scon`, ufw, security updates with 04:30 reboots, Docker, Tailscale (`--ssh`, tag:cloud), OpenSSH off |
| `up.sh` | `plan`, `apply` or `destroy`, with a fresh single-use Tailscale key each run |
| `deploy.sh` | From Trillian or Anjie: copy this folder to `eddie:~/eddie`, with `scon-fetch` and the site book in `vendor/`, and run `install.sh` there |
| `install.sh` | On eddie: ntfy up and served on 443, watchdog timer on, browser up and smoke-tested. Idempotent |
| `services/ntfy/` | ntfy v2.11.0, localhost:8491, published by `tailscale serve` |
| `services/browser/` | Headless Chromium that Claude drives through the Playwright MCP server, on `127.0.0.1:8931`; its only way out is the `scon-fetch` proxy, which applies the site book (README there) |
| `services/watchdog/` | Every 5 min: Homepage, Trillian and Deepthought online (Loki once it listens on the tailnet). Pushes "Down"/"Back" after two failures |

## First build

Order matters: the tag has to exist before a key can carry it.

1. **Scon:** DigitalOcean account with 2FA, card, a $40 billing alert, and a Personal Access
   Token `scon-cloud` with custom scopes (droplet, ssh_key, firewall, tag, regions; read,
   create, update, delete). Store it with `projects/_project-meta/scripts/secret-send digitalocean-scon-cloud` (all machine keys;
   on 2026-10-29 `keys/trillian2.pub` turned out not to be Trillian's key, so don't name a host until that's fixed).
2. **Merge and apply the tailnet policy** that adds `tag:cloud` (`projects` PR). Applying it
   needs Scon's direct word, as always.
3. **On Trillian:** OpenTofu is installed by snap (`/snap/bin/tofu`; add `/snap/bin` to PATH in non-login shells), then
   ```bash
   EDDIE=~/work/scon-hosts/hosts/eddie
   export DIGITALOCEAN_TOKEN="$(~/work/_project-meta/scripts/secret-get digitalocean-scon-cloud)"
   $EDDIE/up.sh plan
   $EDDIE/up.sh apply      # only after Scon says "apply"
   ```
4. Wait about 3 minutes, then `tailscale ssh scon@eddie` (from Anjie, the phone or a home server) and check:
   `test -f /var/lib/scon-cloud-init-done`, `sudo ufw status`, `tailscale status`,
   `systemctl is-active ssh` (should be inactive).

## Break glass

If the tailnet can't reach it: DigitalOcean console → Droplets → eddie → Access → Recovery
Console. Or `up.sh destroy` then `up.sh apply`: nothing on it is precious, and the jobs come
back from the registry.

## State and secrets

- OpenTofu state is in `~/.local/state/scon-cloud/` on whichever host ran `up.sh` (Trillian).
  It holds the droplet id and an already-expired single-use Tailscale key. Not in git.
- The droplet's user data (readable from inside the droplet) holds the same expired key.
- Job secrets come later: Bitwarden Secrets Manager project `host-cloud` once greenfield step 5 is
  live, an age file until then. Only what eddie's jobs need: ntfy, a GitHub deploy key, the
  Claude login.

## Built 2026-10-29

Droplet 614001618, `sfo3`, public IPv4 137.184.38.228 (nothing listens on it but Tailscale),
tailnet 100.106.201.48. Tofu state on Trillian in `~/.local/state/scon-cloud/`.

## What runs here (in this order)

1. ntfy, served on `https://eddie.batfish-pride.ts.net` by `tailscale serve`; `scon-push` and
   `call-reminders` repointed with `SCON_PUSH_NTFY` / `CALL_REMINDER_NTFY` (call reminders
   only with Scon's OK).
2. Outside-in watchdog and dead-man's switch.
3. Your Move runner (`projects/your-move/`, PR #160): one live runner at a time.
4. `scon-digest`, `mailbox-notify`, Claude Remote Control, the jobs registry reconcile.
5. The browser Claude can drive (`services/browser/`, Scon's pick 2026-10-30).
