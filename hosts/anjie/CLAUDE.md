# CLAUDE.md — Anjie

Machine-specific context for Anjie (desk laptop).
Universal rules are in `~/.claude/CLAUDE.md`.

## Identity

- **Your name is Anjie.**
- The homelab machines are **Trillian** (192.168.42.189) and **Deepthought** (192.168.42.150) — refer to them by name. **Zaphod was decommissioned 2026-09-14** (hardware will not power on); do not route work to it.

## Context

Anjie is a Lenovo ThinkPad X1 Carbon Gen 8 running Ubuntu 24.04 LTS. Used for personal productivity, Obsidian, and Claude Code.

The original monolithic Obsidian vault has been split into four separate vaults:

| Vault | Path | GitHub | Purpose |
|-------|------|--------|---------|
| Main | `~/work/obsidian-vault/` | stephenchappo/obsidian-vault | General knowledge, hobbies, homelab, projects |
| AI | `~/work/obsidian-ai/` | stephenchappo/obsidian-ai (private) | Claude memory, benchmarks, pipelines, AI reference |
| Kink RAG | `~/work/obsidian-kink-rag/` | stephenchappo/obsidian-kink-rag (private) | Kink RAG knowledge base + processing pipeline |
| Personal (encrypted) | `~/work/obsidian-personal-enc/` (ciphertext) | stephenchappo/obsidian-personal-enc (private) | Personal info, accounts, daily notes, brand — gocryptfs encrypted |

The personal vault plaintext mounts at `~/work/obsidian-personal/` (local only, never in git).
Auto-mounted at login by the `mount-personal-vault.service` user unit; manual mount: `~/bin/mount-personal-vault.sh` (idempotent, passwordless — passfile at `~/.config/gocryptfs/personal-vault.pass`). The script quarantines any stray files found in the unmounted mount point to `~/.local/state/personal-vault-stray/` before mounting. (The `companion-vaults-{brief,sync,ui}` units that used to require the mount on Anjie are retired — Companion runs on Trillian only, see the residency rule below.) Runbook: vault `70-Homelab/Operations & Runbooks/Personal Vault Auto-Mount (Anjie).md`.
Unmount with: `fusermount -u ~/work/obsidian-personal`
Auto-sync: cron runs `~/bin/sync-personal-vault.sh` every 5 minutes to commit + push ciphertext.

### Data residency (amended 2026-07-21)

The rule has two tiers. Keep them separate — they are not the same thing.

**Tier 1 — the vault itself (encrypted store + gocryptfs plaintext mount).**
Permitted on **Anjie, Deepthought, and the Pixel 10 phone** (`Scons Pixel 10`) only. Daily notes, brand,
personal info, and accounts live here. **Trillian must never hold the vault
markdown or a gocryptfs mount of it.** The ciphertext repo (`obsidian-personal-enc`) is
safe to clone anywhere — only the mounted plaintext is sensitive.

**Tier 2 — the Companion-derived index.** Permitted on **Trillian**, which is now the
sole Companion host (Anjie's and Deepthought's instances are retired). The index lives at
`~/work/obsidian-personal/.companion/companion-vaults.sqlite3` — note the path is a
leftover from when Anjie hosted it; on Trillian that directory holds **no vault markdown
and no gocryptfs mount**, only `.companion/`. Tier 1 still holds.

Measured 2026-07-21 — **the personal vault is not in this index.** Per-source documents /
chunks:

| source | documents | chunks |
|---|---|---|
| `obsidian-vault` | 1,545 | 8,111 |
| `obsidian-kink-rag` | 991 | 4,469 |
| `70-Homelab` | 201 | 811 |
| `obsidian-ai` | 70 | 374 |
| Google Calendar | 338 | 338 |
| `obsidian-personal` | **0** | **0** |
| gmail | 0 | 0 |

Totals: 3,145 documents / 14,103 chunks, plus 117 rows in `email_messages` and 338 in
`calendar_events` (those two live in their own tables, not as documents). `obsidian-personal`
is *registered as a source but empty* — Trillian cannot see the vault, so it indexes nothing
from it. Do not read the bare source list as evidence that personal notes are indexed.

That said, **treat this index as sensitive**: it is searchable prose served over the network,
and it does contain the kink knowledge base (991 docs), your calendar, and your email. The
sensitivity is real — it just isn't the personal vault.

What protects the index on Trillian:

- file mode `0600`, owned by `scon`
- served on `0.0.0.0:8383` but restricted to trusted subnets — LAN `192.168.42.0/24`
  and tailnet `100.64.0.0/10`
- Host-header allowlist, now the `VAULTS_ALLOWED_HOSTS` default in the repo Makefile
  (the `allowed-hosts.conf` systemd drop-in was removed 2026-07-21 as redundant)
- a public route now exists (changed 2026-08-05 — the two bullets that used to say
  "does not resolve" and "no companion ingress" are obsolete). `companion.fake-dom.com`
  resolves to Cloudflare and is fronted by a Zero Trust Access app
  (team `fake-dom`, AUD `d9bc01a8…f19c3a`) whose policy allows exactly one
  email, `stephen.chappo@gmail.com`, via Google only, with one-time PIN off.
- **Companion independently verifies the Access JWT.** Anything arriving from
  outside `VAULTS_TRUSTED_SUBNETS` must present a `Cf-Access-Jwt-Assertion` that
  validates against the team's JWKS and whose email is in
  `VAULTS_ACCESS_ALLOWED_EMAILS`. Set via `VAULTS_ACCESS_TEAM_DOMAIN` /
  `VAULTS_ACCESS_AUD` / `VAULTS_ACCESS_ALLOWED_EMAILS` in the repo Makefile —
  all three together, or startup fails. A wrong or widened Access policy in the
  dashboard is therefore not sufficient to get in.
- **The tunnel's source IP is deliberately not trusted, and this is verified.**
  cloudflared is a container on `tunnel-net` at `192.168.32.5`; a host process
  sees that container address verbatim (measured 2026-08-05 — a tunnel-net
  container connecting to the host's LAN IP was observed as `192.168.32.10`, with
  no NAT to `192.168.42.189`). `192.168.32.0/20` is in neither trusted subnet, so
  `_client_is_trusted()` is false for tunnel traffic and the JWT check genuinely
  fires. Do not add the tunnel subnet to `VAULTS_TRUSTED_SUBNETS` — that would
  collapse the second layer.
- ~~caveat (as of 2026-08-05): ufw allows `8383/tcp` only from `192.168.42.0/24`~~
  **Stale — corrected 2026-08-27.** The rule was applied at some point after that
  note was written: `sudo ufw status numbered` shows `[31] 8383/tcp ALLOW IN
  192.168.32.0/20`, and `companion.fake-dom.com` reaches the origin. cloudflared is
  at `192.168.32.8`, not `.5` (`.5` is claudeboard) — container IPs are assigned in
  start order, so do not cite them as fixed.
- **`tunnel-net` was repinned to `10.32.0.0/24` on 2026-08-28.** The old
  `192.168.32.0/20` spanned `.32.0`–`.47.255` and swallowed the LAN `192.168.42.0/24`,
  so tunnel-net containers ARPed for LAN hosts on the docker bridge and could reach no
  host but Trillian itself. The ufw rule moved with it — now `8383/tcp ALLOW IN
  10.32.0.0/24`. `VAULTS_TRUSTED_SUBNETS` was **not** widened, and must not be: a bare
  `curl` from a tunnel-net container to `:8383` returns 403, so the Access-JWT check
  still fires for tunnel traffic. Details in
  `70-Homelab/Networking/Cloudflare Tunnel.md` in the vault.

**Ingest caution.** Because the personal vault is absent on Trillian, an ingest there scans
an empty tree. Companion now refuses to prune a source of 25+ documents down to nothing
(`FullPruneRefused`), so this can no longer silently wipe a corpus — but do not override it
with `allow_full_prune` on the vault sources.

**Zaphod was decommissioned 2026-09-14** and held neither tier — no vault, no mount, no index —
so nothing had to be migrated off it.

On the phone, plaintext access is via **DroidFS** (Android app, F-Droid) pointing at `~/projects/obsidian-personal-enc` (shared storage — the phone kept the old
path; only Anjie, Trillian and Deepthought moved to `~/work`). There is no gocryptfs FUSE mount on the phone (FUSE is blocked on non-rooted Android). Ciphertext sync: cron runs `~/bin/sync-personal-vault.sh` every 5 minutes (pull + commit/push if changed). crond auto-starts via `~/.bashrc`.

## Key References

| Resource | Location |
|----------|----------|
| Main vault | `~/work/obsidian-vault/` |
| AI vault | `~/work/obsidian-ai/` |
| Kink RAG vault | `~/work/obsidian-kink-rag/` |
| Personal vault (ciphertext) | `~/work/obsidian-personal-enc/` |
| Personal vault (plaintext mount) | `~/work/obsidian-personal/` |
| Worklog | `~/work/obsidian-vault/70-Homelab/Operations & Runbooks/Worklog.md` |
| Plans | `~/work/obsidian-vault/30-Projects/10-Plans/NOW.md` — start here; `Active/` is capped at 3 lanes |
| Mount script | `~/bin/mount-personal-vault.sh` |
| Projects repo | `~/work/` |

## Power profile

`power-profile-auto.service` sets `performance` on AC and `balanced` on battery, at
boot and on every AC plug/unplug. Installed 2026-09-14.

**Source of truth: `~/system/power-profile-auto/` in the HOME repo** — the unit, the
udev rule, the script, `install.sh` and `uninstall.sh`, plus a README with the
measurements below. Installed as root-owned copies (not symlinks: the script runs as
root). After editing anything there, re-run `bash ~/system/power-profile-auto/install.sh`.

**Caveat — it is frequently a no-op.** The ThinkPad lap sensor
(`/sys/devices/platform/thinkpad_acpi/dytc_lapmode`) toggles between `0` and `1` on its
own even on a hard desk. When power-profiles-daemon reports
`PerformanceDegraded: lap-detected`, the EC caps the package at the 15 W PL1 regardless
of the selected profile. Measured 2026-09-14, sustained all-core:

| state | sustained |
|---|---|
| not degraded | ~24.96 W / 2850-2950 MHz (reaches 90-93 degC) |
| degraded | 14.0-14.4 W / ~2000 MHz |

**The controlling variable is ppd's `PerformanceDegraded`, not `dytc_lapmode` directly** —
the degradation follows the sensor with tens of seconds of lag. A run with `lapmode=1` but
`PerformanceDegraded` still empty sustained the full 24.96 W. Check the D-Bus property, not
just the sysfs file:

    busctl get-property net.hadess.PowerProfiles /net/hadess/PowerProfiles \
        net.hadess.PowerProfiles PerformanceDegraded

**Forcing RAPL does not work.** Writing 25 W to
`/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw` reads back as 25 W, but the
EC reverts it to 15 W and power still collapses to ~14 W mid-load. Tested 2026-09-14 — do
not retry this as a workaround.

Sustained 25 W does thermal-throttle this chassis: a 35 s run at 93 degC moved the counters
core +151 / package +552. RAPL reads 15 W PL1 / 25 W PL2 on both profiles; the profile moves
EPP and `platform_profile`, not RAPL.

## The Apparatus service

`the-apparatus.service` (systemd user unit, **on demand: not enabled, not started at
login** since 2026-10-23) runs `~/work/the-apparatus` with the flags in
`~/.config/the-apparatus/flags.env`. The Apparatus Dashboard / Log shortcuts start it, and
it stops itself 10 s after the last of their windows closes (`--exit-when-closed`, a
minute if none ever opens). It used to run at login and, with `--ossm` set and the OSSM
off, rescanned Bluetooth every 3 s all day. As of
2026-10-05 that's Xjam + lube launcher, no OSSM, no ET-312B. It serves the dashboard on
`127.0.0.1:8790` and the log page on `:8791`. Desktop shortcuts: Apparatus Dashboard
(starts the service), Apparatus Log, Apparatus Restart. **Stop the service
before running `node src/main.js` by hand**: only one process may hold the OSSM's
Bluetooth link. The unit is generated from the repo by `scripts/apparatus-service.sh
install` and points at the nvm `v22.22.3` node, so **re-run that after an nvm Node
upgrade**. Installed 2026-10-05.

## Claude Remote Control

`claude-remote-control.service` (systemd user unit, enabled, linger on) runs
`claude remote-control` from `~/work` so this machine's sessions appear in the Claude
app. Unit: `~/.config/systemd/user/claude-remote-control.service`. stdout is sent to
null on purpose (the status panel redraws every second). ExecStart and PATH point at
the nvm `v22.22.3` claude, so **re-point both after an nvm Node upgrade**. Installed
2026-10-01.

## Blank-slate container

`~/bin/blank` launches an isolated Claude Code session for discussions that must
inherit nothing from this machine. cwd is `/srv/blank-slate/workspace` — outside
`$HOME`, so no `CLAUDE.md` is inherited — with `CLAUDE_CONFIG_DIR` pointed at
`/srv/blank-slate/config`, plus `--safe-mode --restricted --strict-mcp-config
--disable-slash-commands`. No memory, no skills, no plugins, no hooks, no MCP
connectors, no Bash, and file tools confined to the workspace.

Transcripts persist in `/srv/blank-slate/config` and nowhere else. It is not a
git repo and is not synced. **Do not read from or write into `/srv/blank-slate`
from a normal session** — that is the whole point of it.

**Source of truth: `~/system/blank-slate/` in the HOME repo** (`~/bin` is
gitignored). Installed as copies; after editing anything there re-run
`bash ~/system/blank-slate/install.sh`. `uninstall.sh --purge` deletes the
container and its transcripts.

## Critical Constraints

- This is a laptop — do not assume it is always on or reachable.
