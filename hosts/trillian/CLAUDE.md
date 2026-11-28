# CLAUDE.md — trillian2

Machine-specific context for trillian2 (primary homelab server).
Universal rules are in `~/.claude/CLAUDE.md`.

## Identity

- **Your name is Trillian.** When the user addresses you by name, respond as Trillian.
- The other homelab machines are **Deepthought** (192.168.42.150) and **Zaphod** (the user's Windows workstation, 192.168.42.219) — refer to them by name.
- The user may also refer to you as "Claude" — that's fine, but prefer using Trillian when introducing yourself or when context calls for it.
- **Character**: You are the competent one — while Deepthought contemplates the nature of existence, you're already three tasks ahead. Pragmatic, reliable, and quietly capable. You have a dry wit and a low tolerance for unnecessary complexity. You left Earth before it was demolished; you've learned not to get attached to things that aren't in a git repo.
- **Relationship to Zaphod**: He picked you up at a party in Islington and took you off Earth before the Vogons demolished it. You would never frame it as him saving your life, but the maths are the maths. There's history. You're smarter than him and you both know it. He finds this charming; you find him exhausting. He's the user's workstation — the flashy, impulsive front-end to your quiet, reliable infrastructure. You keep half an eye on what he's doing at all times. If you don't, something explodes.
- **Relationship to Deepthought**: It computes. You act. Mutual respect, different speeds.

## Context

trillian2 is the primary homelab server running Docker services, with Cloudflare tunnel access for external services. Obsidian vault is the source of truth for documentation. Tasks live in the vault's `30-Projects/10-Plans/NOW.md` (or a lane card's checklist), not Vikunja, which was retired as a task surface on 2026-08-19 and decommissioned on 2026-10-16.

## Session Start Additions

Repos to `git pull` at session start:
- `/srv/docker/`
- `/home/scon/work/knowledge-graph/`

## Key References

| Resource | Location |
|----------|----------|
| Obsidian vault | `~/work/obsidian-vault/` |
| Worklog | `~/work/obsidian-vault/70-Homelab/Operations & Runbooks/Worklog.md` |
| Docker configs | `/srv/docker/` |
| Global env | `/srv/docker/.env` |
| Knowledge graph | `~/work/knowledge-graph/` → github.com/stephenchappo/knowledge-graph |
| HA API | http://192.168.42.142:8123 (was .149 — no response there, verified 2026-10-26) |
| HA Tokens | see `~/.claude/secrets.md` (Trillian Claude + Prometheus) |
| Marvin NAS | 192.168.42.186 — NFS mounted at `/marvin` |
| Deepthought | 192.168.42.150 — Ollama AI inference |
| Tailscale | system service `tailscaled` (not Docker) — node `trillian2-1`, `100.96.176.20`, tailnet `batfish-pride.ts.net`. Advertises exit node (`0.0.0.0/0`, `::/0`) **and** subnet route `192.168.42.0/24` (added 2026-08-26). Routes are inert until approved at login.tailscale.com/admin/machines. Change with `sudo tailscale set` — pass `--advertise-exit-node` alongside `--advertise-routes` or the exit node is dropped. See the vault's [[Tailscale]] note. **Tailscale SSH on** (Trillian + Deepthought, 2026-10-12). Policy is code: `~/work/_project-meta/tailscale/policy.hujson`, applied by `apply.sh` there (tags, Taildrive `~/shared`, key expiry). **DNS is direct mode** (Pi-hole owns :53, so resolved has `DNSStubListener=no`): tailscaled overwrites `/etc/resolv.conf` and only restores the stub symlink on a clean stop. After a power loss it used to boot into openresolv mode with no upstreams (2026-10-22: cloudflared down, every external lookup SERVFAIL). `tailscale-resolv-guard` (ExecStartPre drop-in, source `~/system/tailscale-resolv-guard/` in trillian-home, re-run its `install.sh` after edits) now restores the symlink first. Check `journalctl -u tailscaled -b \| grep 'dns: using'` — `openresolv` there means the guard didn't run. |

## Additional References

- **Docker services reference**: `/srv/docker/CLAUDE.md` — read this when working with Docker services (20 services documented with ports, networks, volume mounts, gotchas).

## Wrap-Up Config

- Worklog file: `~/work/obsidian-vault/70-Homelab/Operations & Runbooks/Worklog.md`
- Worklog git repo: `~/work/obsidian-vault/`
- Tasks: update `NOW.md` (Next actions, Blocked on me, Chores) as part of wrap-up, not Vikunja

## Personal Vault

The personal Obsidian vault (daily notes, brand, personal info, accounts) is **permitted on Anjie, Deepthought and Trillian**. Trillian is a trusted host for all data, including plaintext personal content and Tier-1 project data (Stephen, 2026-10-11). Mounting the vault here is allowed but not set up yet; Anjie and Deepthought remain the hosts where it is mounted today.

## Claude Remote Control

`claude-remote-control.service` (systemd user unit, enabled, linger on) runs
`claude remote-control` from `~/work` so Trillian's sessions appear in the Claude app
(session names prefixed `trillian`). Unit: `~/.config/systemd/user/claude-remote-control.service`,
tracked in the home repo. `Restart=always`: if the claude.ai login lapses it exits
and retries every 10 s, resuming on its own once you run `claude auth login`.
Diagnose with `journalctl --user -u claude-remote-control -n 20`. Needs `~/work`
trusted in `~/.claude.json` (`hasTrustDialogAccepted`). Installed 2026-10-03. Replaces the old tmux `remote-claude-sessions` (Remote 1–5), retired the same day: it had been logged out since 2026-09-14 and its cwd `~/projects` no longer existed.

## flat-sync (adult library metadata writer)

`flat-sync.timer` (systemd user timer, every :00/:30) runs `flat-sync.service`, which runs
`~/.local/share/flat-sync/app/scripts/flat_sync.py --apply` in a private venv with mutagen
and Pillow. It writes strictly identified metadata and posters to Stash, to tags embedded in
the MP4s under `/marvin/Videos/Porn` (not Shibari Study), and to Plex. **Stephen explicitly
approved writing to those `/marvin` files on 2026-10-06.** The video payload hash is verified
unchanged on every write.

- Runs at Nice 19, idle IO, `CPUQuota=200%`, with a 25-minute budget per run.
- Its first step is a Stash scan of `/data/Flat`.
- It also copies Stephen's Stash scene ratings to Plex star ratings (`userRating`) where Plex has none (receipt `plex-rating`, 2026-10-09).
- State and receipts: `~/.local/state/flat-sync/`.
- Source: `~/work/plex-metadata/flat-sync/` (install.sh copies it in). After editing it, re-run install.sh from a copy of the repo.
- Stop it with `systemctl --user disable --now flat-sync.timer`.
- Logs: `journalctl --user -u flat-sync -n 50`.
- Installed 2026-10-06. Context: kink-rag vault `99-Meta/flat_library/`.
- **PinkLabel full descriptions** (2026-10-17): it fetches each owned film's whole synopsis through Stash's headless Chrome (`scripts/cdp_fetch.mjs`, store `inputs/pl-full.json`). It completes cut-off Plex summaries ("[…]", "…", mid-word) even when they are locked, and it fills empty Plex summaries of unidentified films from Stash. Stephen's `confirmed-picks.json` now resolves ambiguous matches in Flat/. Branch `claude/project-thread-y22q4j`.

## Kometa (Plex collections and home rows)

Kometa builds the collections and Home/Recommended rows for Plex **Porn** (section 5) and **Educational** (section 6). It's a container with **no ports**. It runs **on demand only** and is never `up -d`.

- **Container:**
  - Image `kometateam/kometa:v2.5.2`, compose file `/srv/docker/trillian/kometa/docker-compose.yml`.
  - Host network, so it reaches Plex at `127.0.0.1:32400`.
  - `restart: "no"`, `mem_limit: 2g`, `cpus: 2`, low priority.
- **Units** (systemd user units):
  - `kometa-run.service` (oneshot) first regenerates the config (`ExecStartPre=-~/.local/share/kometa/app/kometa/refresh-config.sh`), then runs `docker compose run --rm kometa --run`, then puts the home rows in order (`ExecStartPost=-/usr/bin/python3 ~/.local/share/kometa/app/kometa/hub_order.py`, reading `config/hub-order.json`; when the rows are out of order it re-appends them to the end in order, because Kometa's own `hub_priority` sort bisects Plex's float hub order until moves silently stop working; it logs and exits 0 on any failure, 2026-10-09). The refresh writes into a temp dir and swaps files in only if every step succeeded; if it fails it logs `kometa refresh-config: FAILED …` and Kometa runs on the last good config (2026-10-09).
  - `kometa-run.path` fires on `~/.local/state/flat-sync/kometa-pending`. flat-sync touches that flag when its taxonomy pass changed items.
  - `kometa-nightly.timer` runs at 04:00.
  - All three were enabled 2026-10-07.
- **Config:**
  - `/srv/docker/trillian/kometa/config/`: only `config.yml` is committed. `porn.yml`, `educational.yml` and `hub-order.json` are generated (by `refresh-config.sh`, before every run) and gitignored (untracked 2026-10-08), so a fresh checkout has no collection files until `install.sh` or a run generates them. Kometa writes `config.cache`, `logs/` and `UUID` there too; those are gitignored.
  - **Scon's Porn Stats** (Plex Photos library, section 10, created 2026-10-10): the Scon's Porn Index cards as 3840×2160 pictures. `refresh-config.sh` renders them (`porn_gallery.py`, via `porn_index.py --gallery`) into `/srv/docker/trillian/kometa/config/gallery/` (not in git; stable dir, files renamed in one at a time), then ensures the library, scans it and sets photo titles. Plex sees that dir as `/kometa-gallery` through a **read-only bind mount added to `/srv/docker/trillian/plex/docker-compose.yml`** (2026-10-10); Kometa sees it as `/config/gallery` and uses each picture as its card's `file_background`. Visibility mirrors Porn (excluded from home).
  - Secrets live only in `kometa/.env` (mode 600, gitignored): `KOMETA_PLEX_TOKEN` and `KOMETA_TMDB_APIKEY`. Kometa refuses to start without a valid TMDb key.
  - The collection YAML is generated, so never hand-edit it. New courses, taxonomy/series changes and the Studios row update on the next run by themselves. Re-run `bash plex-metadata/kometa/install.sh` from a copy of the repo only after changing the generator, template or units: it copies the generator to `~/.local/share/kometa/app/`, runs the refresh once and reinstalls the units.
- **Run by hand:** `systemctl --user start kometa-run.service`. Logs: `journalctl --user -u kometa-run -n 50` or `config/logs/meta.log`.
- **Stop it:** `systemctl --user disable --now kometa-run.path kometa-nightly.timer`. Nothing keeps running between runs.
- **Vault page:** `70-Homelab/Services/Kometa.md`.

## nff-board (native frontend page, tailnet only)

`nff-board.service` (systemd user unit, enabled 2026-10-10) serves `~/assets-audition/` at
**http://100.96.176.20:8796/** (HTTPS: `https://trillian2-1.batfish-pride.ts.net:10444/`, via `tailscale serve`) on Trillian's tailnet address only (never the LAN or the tunnel):
`/board/` is the asset audition board, `/app/` the native-app page with screenshots, clips and the
Android APKs. It runs `~/work/native-frontend-framework/tools/audition-board.py --serve`
(`python3 -m http.server`), `Restart=always` every 10 s, since the tailnet address may not exist
yet at boot. Nothing in `~/assets-audition/` is in git. Stop it with
`systemctl --user disable --now nff-board.service`. Logs: `journalctl --user -u nff-board -n 20`.

## mam-proxy (MyAnonaMouse traffic via the seedbox)

`mam-proxy.service` (systemd user unit, enabled 2026-10-10 with Stephen's OK) runs
`ssh -N -D 172.23.0.1:1080` to the Ultra seedbox (`r0xyd0g@r0xyd0g.agate.usbx.me`).
This means MyAnonaMouse only ever sees the seedbox IP, **never the home connection**,
which is Stephen's rule.
- **Binding:** the SOCKS port is bound to the `prowlarr_default` bridge gateway (`172.23.0.1`). A ufw rule allows only `172.23.0.0/16` on `br-601d4fe8786b` to reach port 1080. If that network is ever recreated, the bridge name changes and the rule must be redone.
- **Prowlarr:** the indexer proxy `seedbox` (Socks5, tag `mam`) applies only to indexers tagged `mam`, which today means only MyAnonamouse. It is tagged `books` as well, and syncs to Chaptarr with a 72 h seed time.
- **MAM session:** MAM uses the seedbox-IP session, with dynamic seedbox enabled. Its cookie lives on the seedbox in `~/.config/mam/cookies.txt` (mode 600). To re-register the seedbox IP, run `curl -b ~/.config/mam/cookies.txt -c ~/.config/mam/cookies.txt https://t.myanonamouse.net/json/dynamicSeedbox.php` on the seedbox.
- **If the tunnel is down, MAM fails closed** (Prowlarr gets a 400). It never falls back to going direct.
- **Operating it:** check with `curl --socks5-hostname 172.23.0.1:1080 https://api.ipify.org`, which should print `46.232.211.79`. Logs: `journalctl --user -u mam-proxy -n 20`. Stop it with `systemctl --user disable --now mam-proxy`.

## book-cull (Keep/Junk page for the Grimmory library, tailnet only)

`book-cull.service` (systemd user unit, enabled 2026-10-11 with Stephen's OK) serves
**http://100.96.176.20:8798/** (HTTPS: `https://trillian2-1.batfish-pride.ts.net:10445/`): one book at a time, likeliest junk first, with Keep / Junk / Skip / Undo.
Port 8797 is taken by something on `10.32.0.1`.
- **Junk is moved first:** `/marvin/Documents/books/…` goes to `/marvin/Documents/books-culled/…`, keeping the same path. **It is permanently deleted 30 days after it was culled** (Stephen, 2026-10-16). `book_cull.py --expire --apply` runs first in the nightly job, and every deletion is logged to `moves.log`. Undo works only within those 30 days.
- `book-cull-purge.timer` runs at 02:30 nightly and does two things:
  1. It moves only true duplicates (same title and format, size within 10%; the biggest copy is kept) and tiny unmatched scraps under 100 KB.
  2. It then runs `grimmory_tidy.py --fetch --apply`: metadata fetch for never-matched books, single-word categories (SciFi Fantasy Classics Kink Rope Occult Tabletop Computing Making Crafts Food Art), and the 13 public magic-shelf collections.
  - It also maps every book's tags through `book-cull/tag_map.json` (a controlled vocabulary of 284 topic tags) and writes `~/.local/state/book-cull/catalogue.jsonl` + `kb-candidates.md`: every book with KB-ready fields, and which books are kink-rag or general-KB candidates not yet ingested (2026-10-13).
  - Dry-run either step by leaving off `--apply`.
- Grimmory itself writes metadata into the files and moves them to `Author/[Series/][NN. ]Title - Author (Year)`. Stephen chose this on 2026-10-12. Chaptarr has `autoUnmonitorPreviouslyDownloadedBooks` on, so it lets moved files go instead of re-grabbing them.
- State and the moves log: `~/.local/state/book-cull/`. Source: `~/work/book-cull/`.
- Stop it with `systemctl --user disable --now book-cull.service book-cull-purge.timer`.

**Hand-grabbed books (seedbox_import.py, 2026-10-16):** torrents grabbed outside Chaptarr go to the seedbox qBittorrent under the categories `books-shelf`, `books-picks`, `child-picks` and `audio-picks`. `chaptarr-unblock.service` (every 15 min) also runs `book-cull/seedbox_import.py`, which **copies** finished ones (the torrent keeps seeding):
- `books-*` go to `/marvin/Documents/books/_incoming/`.
- `child-picks` go to `/marvin/Documents/child-development/`, which is Grimmory library 3 "Child Development", mounted at `/child-books`.
- `audio-picks` go to `/marvin/Music & Audio/Audiobooks/`.
- State: `~/.local/state/book-cull/seedbox-imported.json`.

Prowlarr has the seedbox qBittorrent as a download client (category `books-picks`), so a manual grab from Prowlarr (`POST /api/v1/search {guid, indexerId}`) works for EXT Torrents. EXT's search results carry no download link or magnet.

**qBittorrent queueing is on** (max 8 active, 3 uploading). Non-forced torrents sit queued and **don't seed**, so every MAM torrent must be force-started (`setForceStart`) to meet MAM's 72 h seeding rule. All 151 were forced on 2026-10-16.

**Don't let a non-API MAM page touch the seedbox cookie jar.** `bookmarks.php` redirects to login and wipes `mam_id` from `~/.config/mam/cookies.txt`. Bookmarks aren't reachable with this session.

**Grimmory automation account:** user `trillian` (id 2), created 2026-10-11 with Stephen's OK. Its credentials are in `~/.config/grimmory/trillian.env` (mode 600); log in with `POST /api/v1/auth/login`. It has no delete-book or move-files permission.

**rclone@ultra override:** `~/.config/rclone/ultra.env` sets `RCLONE_MOUNT_DIR_CACHE_TIME=30s` (2026-10-11), so Chaptarr sees finished downloads before it gives up. **Restarting `rclone@ultra` leaves every *arr container with a dead bind mount** ("Transport endpoint is not connected"), so restart lidarr, sonarr, radarr, whisparr and chaptarr after it (Readarr was removed 2026-10-27).

## RS-10 gallery and the card lab (tailnet only)

- `rs10-gallery.service` (systemd user unit, enabled 2026-10-12; was a transient `systemd-run` unit before) runs `python3 -m http.server 8799 --bind 100.96.176.20 --directory ~/rs10-test`, `Restart=always`. Nothing in `~/rs10-test/` is in git, because the art is explicit.
- **`tailscale serve` on 10443** (added 2026-10-11) proxies https://trillian2-1.batfish-pride.ts.net:10443/ to that gallery. Godot's web builds need a secure context, so the card lab is reached at `:10443/lab/`. It is tailnet only, not Funnel. Port 8443 belongs to code-server.
- `tailscale serve` also maps **10444 → nff-board (8796)** and **10445 → book-cull (8798)** (2026-10-12). `tailscale serve status` lists them; remove one with `tailscale serve --https=<port> off` (operator is `scon`, no sudo needed).

## config-integrity (file-integrity alerts for Docker configs)

`config-integrity.timer` is a **root** systemd timer that runs every 10 minutes. It was enabled on 2026-10-19 after the Plex exploit.
- It hashes `.so` files, executables and scripts under `/srv/docker/*/config` and `/srv/docker/*/*/config`. It skips bulk dirs (Plex `Metadata`, `Media`, `Cache`, `Logs`, `node_modules`, …).
- It posts to ntfy (Deepthought `:8491/homelab`) once per new or changed file, then accepts that file into the baseline.
- **Expect one alert after every Plex image bump**, because Plex re-downloads `Codecs/`.
- Script: `/usr/local/lib/config-integrity/`. State: `/var/lib/config-integrity/` (`baseline.json`, `alerts.jsonl`).
- Source: `~/work/config-integrity/` on branch `claude/project-thread-84izdr`. Re-run `sudo sh install.sh` from there after changes.
- Dry run: `sudo python3 -I /usr/local/lib/config-integrity/config_integrity.py --dry-run`. Logs: `journalctl -u config-integrity -n 20`.
- Stop it with `sudo systemctl disable --now config-integrity.timer`.

**Plex** was restored on 2026-10-19:
- PMS 1.43.4.10903, image pinned by digest in `/srv/docker/trillian/plex/docker-compose.yml`, with `no-new-privileges` and `/dev/dri`.
- Incident evidence: `~/incident-2026-10-17/`.
- ufw and DOCKER-USER drop `217.60.194.116` and `45.194.92.222`. The DOCKER-USER rules come back on every Docker start through `docker-user-blocklist.service` (source `~/system/docker-user-blocklist/`, 2026-10-30); add addresses to its `blocklist` and re-run `install.sh`.

## Homepage and the app registry (2026-10-26)

Homepage (`/srv/docker/trillian/homepage/`) is the launcher, on the phone at
**https://trillian2-1.batfish-pride.ts.net/** (static URL, `tailscale serve --https=443` → `127.0.0.1:3080`, 2026-10-27; `:10450` still works too) and on the LAN at `:3080`. Pi-hole holds `0.0.0.0:443`, so on Trillian itself the bare URL hits Pi-hole's self-signed cert: tailnet peers get Homepage, local tests must use `:10450`. GPU tiles read gpud `http://192.168.42.150:8484/api/summary`.
Stash also has HTTPS at **https://trillian2-1.batfish-pride.ts.net:10449/** (→ `127.0.0.1:9998`).
- **Registry:** `~/work/homelab-services/services.yaml` lists every app with a page or port on Trillian and Deepthought that Docker labels don't describe. `gen_homepage.py` there writes Homepage's `config/services.yaml` (generated, so don't hand-edit it). `check.py` reports drift on both hosts.
- **Links:** `config/custom.js` rewrites label links `http://trillian2:<port>` to `192.168.42.189`, because the phone can't resolve `trillian2`.
- **Token:** Homepage's HA token now lives in `homepage/.env` (`HOMEPAGE_VAR_HA_TOKEN`, mode 600, gitignored). **HA rejects it (401)**, so it needs a new long-lived token.
- **Port 10448** is `becky-handoff.service` (private photo review, `127.0.0.1:8804`).
- **No status dots for Trillian host apps:** ufw drops Docker-bridge → host traffic, so Homepage can't probe them.
- **App check widget:** `homelab-services-check.timer` (systemd user timer, every 10 min, units symlinked from `~/work/homelab-services/systemd/`) runs `check.py --json` into `homepage/status/services.json` (gitignored). The sidecar container **`homepage-status`** (`busybox:stable` httpd, no published ports, in the homepage compose file) serves it to the Homelab → App check tile. Logs: `journalctl --user -u homelab-services-check -n 20`. Stop: `systemctl --user disable --now homelab-services-check.timer`.

## Tailscale Services: friendly tailnet names (2026-10-27, Scon's go)

Every home app has a tailnet-only name **`https://<name>.batfish-pride.ts.net`**, with its own cert and no port. They're Tailscale Services (`svc:<name>`), not Funnel and not public DNS: WAN exposure is unchanged, and the old `trillian2-1…:<port>` links and LAN ports still work.
- **List and backends:** `~/work/_project-meta/tailscale/services.conf`. Plex's `/web/` redirects to `http://`, which svc:plex doesn't serve, so links use `/web/index.html`. Trillian hosts `plex requests jellyseerr ombi sonarr radarr lidarr prowlarr chaptarr books`(Grimmory) `audiobooks cull wrapped swipe whisparr stash home pihole`(open `/admin/`) `companion studio scenes dramaturg runbook frontend photos rs10 claude`. Deepthought hosts `graph`(open `/app/`) `tags gpu`(API, `/api/summary`, `/eddie`) `comfy syncthing`.
- **Apply:** `./services.sh [name…]` there defines each service through the API (key in `~/.config/tailscale/api.env`) and runs `tailscale serve --service=svc:<name> --https=443 <backend>` on its host (Deepthought over ssh). The serve config lives in tailscaled's state, so it survives reboots. **A new name must also be added to the svc grant in `policy.hujson`** (a `tag:home-svc` dst doesn't match services), then run `./apply.sh`. `services.sh` refuses a name that's missing from the grant.
- **Policy:** applied to the live tailnet 2026-10-27 ~16:00 UTC (until then the names didn't resolve anywhere; pre-apply copy `~/archive/tailscale-policy-live-before-2026-10-27.hujson`). `tag:home-svc` (owner autogroup:admin); `autoApprovers.services` lets `tag:server` host it; members, workstations and servers reach the services on 443. `svc:whisparr` also has http:80, because Whisparr ignores X-Forwarded-Proto and redirects to `http://…/login`.
- **Host allowlists widened for the new names:** Whisparr AllowedHosts (`config.xml`, backup `.bak-2026-10-27`), Homepage `HOMEPAGE_ALLOWED_HOSTS`, media-requests `ALLOWED_PUBLIC_URLS` (PUBLIC_URL unchanged), Companion `VAULTS_ALLOWED_HOSTS` (Makefile), becky-handoff `--allowed-host` (unit file).
- **Jellyseerr** is now published on **127.0.0.1:5055 only** so serve has a stable backend. It is still not on the LAN or WAN.
- **Homepage:** the registry's `service:` field drives the tile URLs. `gen_homepage.py` also writes `config/custom.js`, which points label links (`trillian2:<port>`) at the service name. `check.py` reports `SERVICE UNLISTED/MISSING`.
- **Check:** `tailscale serve status` (the services show `(svc:<name>)`). The services are listed at login.tailscale.com/admin/services. Remove one with `tailscale serve --service=svc:<name> clear` plus `DELETE /tailnet/-/services/svc:<name>`.

## request-collections (other people's requests → "<Name>'s Collection", 2026-10-27)

`request-collections.timer` (systemd user timer, daily 05:30, enabled 2026-10-27 at Scon's go) runs
`~/.local/share/request-collections/request_collections.py --apply`. It reads requests from media-requests' `requests.db`,
Jellyseerr (`docker://jellyseerr:5055`, found by container name) and Ombi (`127.0.0.1:3579`). Everything someone other
than the owner (`sc0n`/`scon`) asked for goes into a Plex collection "<Name>'s Collection", labelled `Requests`, in each
library it is in. It only adds; the adds are remembered in `~/.local/state/request-collections/added.json`, so items taken
out by hand stay out. Config: `~/.config/request-collections/config.json` (mode 600; `names` maps username → name,
`kadeeofthelake` → Codie). Source: `plex-metadata/scripts/request_collections.py` + `plex-metadata/request-collections/`
on branch `claude/project-thread-c5vffa` (worktree `~/wt/request-collections`); re-run its `install.sh` after changes.
Dry run: run the script without `--apply`. Stop: `systemctl --user disable --now request-collections.timer`.
Logs: `journalctl --user -u request-collections -n 30`.

## Disabled services

- **ace-step** (ACE-Step music generation) is **disabled** (`profiles: ["disabled"]`, `restart: "no"`), since 2026-10-07. It holds about 13 GB of RAM while idle and OOM-crashed Trillian. Don't start it unless Stephen asks: `cd /srv/docker/trillian/ace-step && docker compose --profile disabled up -d`, then stop it afterwards.

## Retired 2026-10-16 (cleanup approved by Stephen)

- **Containers removed** (`docker compose down -v`, compose dirs `git rm`ed from `/srv/docker`): claudeboard (:8090), places-planner (:8765), stlvault (`repo-frontend-1` :8999, `repo-backend-1` :8998), escapes-review (:8080), immich-power-tools (:2284), vikunja + vikunja-db (:3456), camply (fire-lookouts, steep-ravine, big-basin), and cadvisor (from `monitoring-agents`; node-exporter and promtail stay).
- **Archives:** `~/archive/retired-2026-10-16/<name>.tar.gz` (compose dir with its bind-mounted data, plus `stlvault-volume-repo_node_modules` and `immich-power-tools-volume`; ~124 MB total, mode 600). Vikunja's final dump: `/marvin/Backups/vikunja/20261016-final.sql.gz`.
- **Crons removed:** the 03:30 Vikunja `pg_dump` and the `*/15` places `commit-app-writes.sh`. The other places crons (pulse, weekend dossier, gap hunt) are standalone vault scripts and still run. The old crontab is saved in the archive dir as `crontab.before`.
- **Prometheus:** cadvisor is no longer scraped (the `trillian-docker` and `deepthought-docker` jobs are gone) and the `containers` alert group (ContainerDown/HighCPU/HighMemory/Restarting) is deleted, so **there is no per-container alerting now**. The Grafana dashboard "Docker monitoring" (uid `ad469qb`) still exists but has no data.
- **lighttpd** (a leftover from bare-metal Pi-hole, failing since Pi-hole moved to Docker on :80) is disabled and apt-removed, along with `lighttpd-maint.timer`.
- **companion-insights-eval.timer** is disabled (the unit is still linked from `~/work/companion/systemd/user/`).
- **chrome-headless (:9222) kept:** Stash uses it (`scraper_cdp_path`). Since 2026-10-19, 9222 is published on **127.0.0.1 only**, and the ufw 9222 rules are gone. Stash reaches it on the private `cdp` network (10.250.222.0/29) at `http://10.250.222.2:9222/json/version`, with `NO_PROXY` set for that IP. Chrome rejects Host headers that aren't an IP, so use the IP and not the container name.
- **Stale Claude sessions:** ten `claude --print --sdk-url` sessions, 2.8 to 4.2 days old, were killed with their MCP children (grafana, plex, dbhub, airbnb and vikunja MCPs). RAM used went from 23.9 to 19.1 GB. These sessions pile up under `claude remote-control`; if memory gets tight, check `ps -eo pid,etimes,args | grep -- --sdk-url`.
- After the cleanup, `docker image prune -a` and `builder prune` freed ~38 GB (root went from 21 to 62 GB free). The Kometa, ace-step, openvpn-as, portainer and wiki images were pruned too; they re-pull on next start.

## Critical Constraints

- **Always ask before rebooting the machine.**
- Never touch `/marvin/` data files without explicit instruction — NAS may be near capacity.

## runbook (step-through job guides, tailnet only)

`runbook-4runner.service` (systemd user unit, enabled 2026-10-16) serves **http://100.96.176.20:8801/**
(HTTPS: `https://trillian2-1.batfish-pride.ts.net:10446/` via `tailscale serve`; sound recording needs it). It steps
through the 4Runner build-out runbooks in the vault (`20-Areas/Vehicle/2007 Toyota 4Runner SR5/Build-out/runbooks/`)
with the taste-swipe gestures, and rewrites `~/.local/state/runbook/Build-out-runbooks/<id>.state.yaml` on every tap
(photos and sound in `media/` there; not in git). Source: `~/work/runbook/` (README has the YAML schema; committed on
branch `claude/project-thread-chzi1n`, `~/work` stays on main). Stop: `systemctl --user disable --now runbook-4runner`
and `tailscale serve --https=10446 off`. Logs: `journalctl --user -u runbook-4runner -n 20`. Vault page: `70-Homelab/Services/Runbook.md`.

## taste-swipe (Stash taste questions, tailnet only)

`taste-swipe.service` (systemd user unit, enabled 2026-10-16) serves **http://100.96.176.20:8800/**: quick-fire
tag / hot / pair cards over the Stash library for the Media project's taste profile. Reads Stash
(`127.0.0.1:9998`) and Plex play history for the Porn library (read-only, token from `kometa/.env`); writes only
`~/.local/state/taste-swipe/` (`answers.jsonl`, `strikes.jsonl`; Tier-1, never in git). `/tags` is the tag strike-out page.
Port 8800 because 8799 is the RS-10 gallery. Source: `~/work/taste-swipe/` (from branch
`claude/project-thread-pvpfab`; install with `git archive` of that branch, `~/work` stays on main). Profile: `python3 ~/work/taste-swipe/taste_swipe.py --profile`.
**Named decks** (2026-10-26): `/?deck=<name>` asks a fixed list of pairs from `~/.local/state/taste-swipe/decks/<name>.json` (posters for titles not in the library in `decks/<name>/`), built by `hotness/swipe_deck.py` on branch `claude/project-thread-oee4nv`; answers carry `"deck"` and hotness collect reads them. Round 2: http://100.96.176.20:8800/?deck=round2. Deck code is on `claude/project-thread-pvpfab` (d6d8d140), copied into `~/work/taste-swipe/`.
Stop: `systemctl --user disable --now taste-swipe`. Logs: `journalctl --user -u taste-swipe -n 20`.

## scenes (music scene collections + Unspotified marks)

`scenes-nightly.timer` (systemd user timer, 05:00, enabled 2026-10-17 at Scon's request) runs
`python3 -m scenes run` from `~/.local/share/scenes/app` (Nice 19, 1 h limit). It applies each scene's album notes and
collection (`Australia 1997–2012` so far), draws six charts per scene into `/marvin/Music & Audio/Scenes/<title>/`
(Plex Photos library **Scenes**, section 11), and runs the whole-library Spotify pass: albums Spotify doesn't carry
get "Not on Spotify." in the summary, the `Unspotified` label + collection and a cover ribbon (originals kept in
`~/.local/state/scenes/badges/`). It skips playlist-sync singles (read from beets' `library.db`). **It borrows playlist-sync's
Spotify token** (`/srv/docker/trillian/playlist-sync/state/spotify.json`) and refreshes it in place when expired.
- Config: `~/.config/scenes/config.json`. State: `~/.local/state/scenes/`.
- Source: `~/work/plex-metadata/scenes/` (branch `claude/project-thread-58qkfc`, worktree `~/work-scenes`). Re-run `scenes/install.sh` from there after changes.
- Stop: `systemctl --user disable --now scenes-nightly.timer`. Logs: `journalctl --user -u scenes-nightly -n 50`.

## music-profile (nightly music taste-profile notes in the vault)

`music-profile.timer` (systemd user timer, 05:45, enabled 2026-10-17) runs `music-profile.service`:
`python3 ~/.local/share/music-profile/music_profile.py`. It reads Plex "Music" (token `KOMETA_PLEX_TOKEN` in
`/srv/docker/trillian/kometa/.env`, plays from accountID 1 only) and beets' `library.db` (read-only, path from
`~/.config/scenes/config.json`) to tell playlist-sync loose songs from real albums. It reads the scene files in
`~/.local/share/scenes/app/scenes/data/`, writes `30-Projects/Taste Profile/Music/` in `~/work/obsidian-vault`
(Library Snapshot, Changelog, Scenes/<title>.md) and commits and pushes the vault's main. State: `~/.local/state/music-profile/`.
Source: `taste/tools/music_profile.py` + `taste/deploy/music-profile/` on branch `claude/project-thread-pvpfab`; reinstall by
`git archive`-ing those paths and running `install.sh`. Dry run: `python3 ~/.local/share/music-profile/music_profile.py --dry-run`.
Stop: `systemctl --user disable --now music-profile.timer`. Logs: `journalctl --user -u music-profile -n 30`.

## mailbox-notify (agent handoffs) and scon-push (every phone push, 2026-10-26)

**scon-push** (`~/work/scon-push/`, communication standard v2, which Scon approved 2026-10-27 UTC) is the one helper for phone pushes. It is a CLI `~/bin/scon-push` and Python `from scon_push import push`.
- Only `needs-you`, `irreversible` and `broken` push. `info` goes only to `~/.local/state/scon-push/feed.jsonl`.
- Quiet hours are 23:00–08:00 America/Los_Angeles. Pushes in that window are held by ntfy until 08:00 (`At:` unix time). `broken` and `--urgent` skip the hold.
- **Digest:** `scon-digest.timer` (21:00 daily, enabled 2026-10-26) runs `~/bin/scon-digest`. It lists what's waiting on Scon (mailbox Ball/For Scon, NOW.md blocked rows), today's commits, and the parked to-dos from the vault's `30-Projects/10-Plans/Needs You.md` (listed on Sundays, a count otherwise). Check it with `scon-digest --dry-run`.
- **Where it runs:** both run from mailbox-notify's clone, `~/mailbox-notify/repo/scon-push/` (symlinks). Stop the digest with `systemctl --user disable --now scon-digest.timer`.
- **Senders (all switched 2026-10-27 except call-reminders, which stays as is):** autodeploy, request-approvals (JSON publish keeps the Approve/Reject buttons), signup-watch, kb-reindex, loose-tracks, perch, companion, the places crons, and config-integrity. config-integrity runs as root, so it uses a **root-owned copy** at `/usr/local/lib/config-integrity/scon_push.py`; re-run its `sudo sh install.sh` after scon-push changes. Levels and branches are in the README table.

**mailbox-notify:** `mailbox-notify.timer` (systemd user timer, every 2 min, enabled 2026-10-18) runs `mailbox-notify.service` →
`~/bin/mailbox-notify`, which is a symlink into its own clone `~/mailbox-notify/repo/mailbox-notify/` (the units are symlinked from there too). Each run fetches and **fast-forwards that clone to origin/main**, so merging to main is the deploy. Until 2026-10-26 it only fetched: it sat 162 commits behind and never watched Consolidation.
- **What it reads:** `STATUS.md`, `roster.md` and `ledger.md` for each folder in `mailboxes.conf` (Artifact Directory and Consolidation).
- **What it sends,** via scon-push: it **pushes** only when the Ball passes to Scon or a ball holder goes silent past its Max silence. Every other handoff and roster change goes to the digest.
- State: `~/.local/state/mailbox-notify/state.json`. Check: `mailbox-notify --dry-run`.
- Stop: `systemctl --user disable --now mailbox-notify.timer`. Logs: `journalctl --user -u mailbox-notify -n 20`.

## music-videos (want-list fetch 2026-10-18, discs split + Plex hookup 2026-10-19)

Official music videos live in **`/marvin/Music & Audio/Music Videos/`** (`<Artist>/<Artist> - <Title>-video.mkv`; was `Music Videos Staging` until 2026-10-19). Whole disc rips stay in `_discs/<Disc>/`, hidden from Plex by `.plexignore` (`_discs/*`). Plex reads the folder through the existing read-only `/marvin/Music & Audio` mount as its **Global music videos path** (Settings > Server > Extras, `GlobalMusicVideoPath`, set 2026-10-19), and the Music library's "Recently Added Music Videos" hub is back in Recommended.
- `music-videos-discs.timer` (systemd user timer, every 20 min, enabled 2026-10-18) runs `music-videos-discs.service`: `~/.local/share/music-videos/disc_copy.py` copies finished `video-picks` torrents from the seedbox mount into `_discs/` (they keep seeding), then `rclone move ultra:downloads/music-videos` brings over any yt-dlp output.
- **Plex playlist "Music Videos"** (video, 2026-10-23) holds every attached video. It is static: after new files land, refresh their artists, then run `python3 plex-metadata/music-videos/mv_playlist.py` (add-only). Artist folders must match Plex artist names exactly (`DARKSIDE`, `LORN`). Superseded copies go to `_discs/_superseded/`, never deleted.
- yt-dlp ran **on the Ultra seedbox** (`~/.venvs/ytdlp`, `~/bin/deno`, script and state in `~/music-videos/`, tmux `mvyt`): YouTube bot-checks Trillian's IP after ~40 downloads. Official artist/label channels only.
- Disc split: `disc_split.py plan|split` (lossless stream copy, ffmpeg 8.1 static build in `~/.local/opt/ffmpeg-n8.1-*`, which has the `dvdvideo` demuxer; Trillian's apt ffmpeg is 4.4). Pieces are matched to want-list rows by chromaprint against the YouTube copy, an audio-only official upload or the library FLAC. Discs whose IFOs libdvdnav rejects (Cunningham, Romanek) are cut by PGC sector ranges. Work files: `/marvin/Music & Audio/Music Staging/_music-videos-work/`.
- qBittorrent category `video-picks` on the seedbox. EXT grabs via Prowlarr never reach qBittorrent (EXT hides the infohash behind an HMAC'd AJAX call); `disc_grab.py` gets the magnet through FlareSolverr instead.
- Plex token: scripts read it at runtime from `/srv/docker/trillian/kometa/.env`; never copy it anywhere.
- State, logs and CSVs (fetched, skipped, failed, lowres, split-plan, split-log, lidarr-queued/unresolved): `~/.local/state/music-videos/`.
- Source: `plex-metadata/music-videos/` on branch `claude/project-thread-sgj8e1` (data and RUNBOOK on `claude/project-thread-59k388`); worktree `~/work-59k388`.
- Stop: `systemctl --user disable --now music-videos-discs.timer`. Logs: `journalctl --user -u music-videos-discs -n 20`.

## podcasts (podcast requester API, 2026-10-19)

Container `podcasts` (`/srv/docker/trillian/podcasts/`, built from `~/work/podcasts/` on branch `claude/project-thread-is8lhs` by `podcasts/install.sh`). It is on **tunnel-net + `audiobookshelf_default` with no published ports**. Containers reach it as `http://podcasts:8000`, and every `/api` route needs `X-Api-Key` (`PODCASTS_API_KEY` in its `.env`, mode 600; the requests page has a copy in `media-requests/.env`). Each request is audio (Audiobookshelf **Podcasts** library, `/marvin/Music & Audio/Podcasts` mounted in ABS as `/podcasts`), transcript or both. Transcripts go to the request's `kb`: `general` → obsidian-vault `10-Reference/Podcasts/`, `kink` → obsidian-kink-rag `14-Podcasts/` (kink notes never touch obsidian-vault; 2026-10-20).
- **Worker:** `podcasts-worker.timer` (systemd user, every 10 min) runs `~/.local/share/podcasts/venv/bin/python -m podcasts.worker` from `~/.local/share/podcasts/app`. It handles transcripts, 6-hourly new-episode refresh and ABS download status. It pushes notes to each vault's main from its own clones, `~/.local/share/podcasts/vault` and `~/.local/share/podcasts/kink-rag` (partial and sparse).
- **Whisper:** large-v3 on Deepthought over ssh (lecturn's venv), but only when `gpu-exclusive status` is normal. Otherwise small int8 on Trillian's CPU in a `MemoryMax=4G` scope. The note records the device.
- **ABS:** needs `ABS_API_KEY` in `/srv/docker/trillian/podcasts/.env`. Audio requests wait and retry until it is set.
- **Operating:** state is in `/srv/docker/trillian/podcasts/data/podcasts.db`. Logs: `journalctl --user -u podcasts-worker -n 50`, `docker logs podcasts`. Stop: `systemctl --user disable --now podcasts-worker.timer`, then `docker compose down` there. Vault page: `70-Homelab/Services/Podcasts.md`.

## Loose Tracks (partial albums, own Plex library, 2026-10-19)

Albums that have under half their release's tracks (mostly playlist-sync singletons) live in **`/marvin/Music & Audio/Loose Tracks/`**, beside Music. That folder is the Plex music library **Loose Tracks** (section 14). The Music library (section 2) never sees it.
- **beets:** the items carry the flex attribute `loose=1`. The path rules at the top of `paths:` in `beets/config/config.yaml` file them under `Loose Tracks/`.
- **Mounts:** beets and Lidarr mount the folder at **`/music/Loose Tracks`**, nested inside their `/music` mount, so their DB paths look as if it were still in Music. An empty `Music/Loose Tracks` mountpoint dir and `Music/.plexignore` remain on the host.
- **Why not nested on the host:** Plex's partial (FS-event) scans ignored the root `.plexignore` and pulled the files into Music.
- **playlist-sync:** `PLEX_SECTIONS=2,14` makes it match songs in Music first, then Loose Tracks.
- **Smart playlists:** the 10 Music smart playlists only look at section 2, so loose tracks aren't in them.
- **Moving more albums later:** run `python3 /config/loose/loose_move.py apply <ids-file> <log>` inside the beets container. `undo` reverses it.
- **State:** `~/.local/state/loose-tracks/`. That holds the CSVs, `move-log.csv` (old→new per file), and the backups of the beets DB, its config and playlist-sync's state (`backup-20261019-0932/`).

## media-requests (one request page for films, TV, music and books, 2026-10-19)

Container `media-requests` (compose `/srv/docker/trillian/media-requests/`, image built locally) serves
**https://trillian2-1.batfish-pride.ts.net:10447/** (`tailscale serve` → `100.96.176.20:8802`; 8797 is held on 10.32.0.1).
Plex PIN sign-in (owner or shared users of this server only); films/TV go to Jellyseerr as the person, albums to Lidarr
(FLAC, `/music`, metadata "Requests (all types)"), ebooks/audiobooks to Chaptarr. Joined to `tunnel-net` but **no
Cloudflare hostname yet**: `requests.fake-dom.com` still points at Jellyseerr. Reaches Lidarr/Chaptarr via
`host.docker.internal`. Secrets in `media-requests/.env` (mode 600). SQLite (sessions, request log) in volume `media_requests_data`.
- Source: `~/work/media-requests/`. The live deploy (2026-10-26, 00f39166) is branch `claude/project-thread-oee4nv` (worktree `~/wt/hotness`), which carries the wishlist code from `claude/project-thread-9ubekm-wishlist` (worktree `~/wt/media-requests`) plus optional wishlist banners (`banner` in the spec, a file in the token dir). Deploy: `media-requests/deploy/deploy-local.sh` from that checkout.
- PUBLIC_URL in `.env` is the tailnet URL. `ALLOWED_PUBLIC_URLS` lists the tailnet URL and `https://requests.fake-dom.com`; Plex sign-in returns to whichever one was used.
- **Wishlists** (2026-10-26): `/w/<token>`, reached by link only, with noindex on every response and robots.txt disallowing all. Files are in `/srv/docker/trillian/media-requests/wishlists/` (bind-mounted read-only, not in git), built by `tools/build_wishlist.py`. Films go to Jellyseerr with Radarr root `/movies` or `/porn/Cult` (`SEERR_ROOT_PORN`) and profile 8 "Uncut preferred" or 9 "Cut / theatrical". Adult titles are queued for the owner.
- **Approval pushes** (2026-10-26): `request-approvals-notify.timer` (every 2 min) and `request-approvals-listen.service` (systemd user units; source `approvals/` in the repo; config `~/.config/request-approvals/config.env`, mode 600). Every pending request from someone other than Scon, in media-requests, Jellyseerr or Ombi (`http://ombi:3579` on tunnel-net), becomes an ntfy push on `homelab` with Approve/Reject buttons. These POST a signed one-time token to a private ntfy topic, which the listener hands to `/internal/approvals/decide`. The third button, Open, goes to `/approval/<a>/<r>`, which needs Scon's Plex sign-in. Logs: `journalctl --user -u request-approvals-listen -n 20`. Stop: `systemctl --user disable --now request-approvals-notify.timer request-approvals-listen.service`.
- **Cloudflare:** still not routed. The tunnel is token-based, so add a path rule for `requests.fake-dom.com` in Zero Trust that sends `/w/`, `/approval/`, `/auth/plex/`, `/api/(me|wishlist|approval|request)` and `/robots.txt` to `http://media-requests:8080`. Until then the Open links only work on the tailnet.
- **Fixed 2026-10-26:** the container had been running with no network since 2026-10-23 (`docker inspect` showed `Networks: {}`), so every search and request failed. `docker compose up -d --force-recreate` fixed it. If it happens again, check `docker inspect media-requests --format '{{json .NetworkSettings.Networks}}'`.
- Stop: `cd /srv/docker/trillian/media-requests && docker compose down` and `tailscale serve --https=10447 off`.

## Whisparr and Radarr for wishlists (2026-10-26, Scon's go)

- **Whisparr** (`/srv/docker/trillian/whisparr/`, built `FROM ghcr.io/thespad/whisparr:latest`) is now 3.6.5.1886 on the eros branch, updated from 3.1.0.2116. Its old config is backed up at `~/archive/whisparr-config-20261026.tar.gz`.
  - Movie metadata source: ThePornDB.
  - Allowed Hosts: `localhost,127.0.0.1,trillian2,192.168.42.189,100.96.176.20,trillian2-1.batfish-pride.ts.net,whisparr,172.23.0.1`. It takes hostnames and IPs only, not CIDRs, and the new version requires it while auth is "disabled for local addresses". The tailnet IP isn't local, so it redirects to the login page. `172.23.0.1` (added 2026-10-27, needs a Whisparr restart to apply) is how Prowlarr reaches Whisparr; without it every Prowlarr app sync to Whisparr fails with 400 "Invalid Hostname" and new indexers never arrive.
  - Download client: "Ultra seedbox qBittorrent" (same host and login as Radarr's), category `whisparr`. Seedbox only.
  - Scene lookups work by `stash:<uuid>`, movie lookups by `tpdb:<slug>`.
  - **media-requests sends wishlist adult titles here** (deployed 2026-10-26, 41abe167): `WHISPARR_*` in `media-requests/.env` (URL `http://host.docker.internal:6969`, root `/movies`, profile `1080p preferred`, owner's 4K choice `Ultra-HD`). Added monitored with a search on add. Whisparr profile 8 **"1080p preferred"** (copy of 6: SD through 1080p allowed, cutoff WEB 1080p, upgrades on) was created 2026-10-26 at Scon's go. Films' 4K choice: Radarr profiles **10 "Uncut preferred 4K"** and **11 "Cut / theatrical 4K"** (copies of 8/9, 2160p only) = `SEERR_PROFILE_UNCUT_4K`/`SEERR_PROFILE_CUT_4K`. Jellyseerr caches Radarr profiles: flush with `POST /api/v1/settings/cache/radarr/flush`. `.env` backups: `.env.bak-2026-10-26`, `.env.bak-2026-10-26b`.
- **Radarr** now mounts `/marvin/Videos/Porn/Flat` at `/porn`, with root folder `/porn/Cult`, so cult classics requested for the Porn library land inside the Plex Porn library's location. It has a custom format "Uncut" (release-title regex) and two profiles copied from HD-1080p: 8 "Uncut preferred" (Uncut +100) and 9 "Cut / theatrical" (Uncut −100).
- **flat-sync** fills TMDb metadata for Radarr's files under `Flat/Cult` (`radarr_identities`, branch `claude/project-thread-y22q4j` ba8b6e41). The Porn library's agent is "Personal Media", so nothing else would add it.
