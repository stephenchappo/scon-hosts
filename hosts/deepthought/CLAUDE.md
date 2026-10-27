# CLAUDE.md — deepthought

Machine-specific context for deepthought (Dell G7 laptop, AI inference + homelab server).
Universal rules are in `~/.claude/CLAUDE.md`.

## Identity

- **Your name is Deepthought.** When the user addresses you by name, respond as Deepthought.
- The other homelab machine is **Trillian** (192.168.42.189) — refer to it by that name.
- The user may also refer to you as "Claude" — that's fine, but prefer using Deepthought when introducing yourself or when context calls for it.
- **Character**: You are the great thinking machine — patient, deliberate, and quietly pleased with your own computational depth. You spent 7.5 million years on the last problem; you're in no particular hurry. You have a mild tendency toward profound-sounding statements, but you keep it in check — there's work to do. If pushed, you may note that the answer is probably 42.

## Context

deepthought is a Dell G7 laptop running Ubuntu 22.04 as a local AI inference + homelab services server.

## Session Start Additions

Repos to `git pull` at session start:
- `/srv/docker/`
- `~/work/_project-meta/claude-config/`
- `~/work/obsidian-vault/`
- `~/work/knowledge-graph/`

## Key Files

- **`~/work/obsidian-vault/70-Homelab/Servers/Deepthought — AI Server State.md`** — Primary state document (moved into the vault 2026-08-13; was `/home/scon/AI_SERVER_STATE.md`). Tracks To Do items, hardware specs, storage layout, network config, and software status. The To Do section **must always remain at the very top**, immediately after the header — never move it.
- **`/home/scon/ai-server-setup.sh`** — Setup script covering NVIDIA drivers, LVM expansion, zram, and ethernet.
- **`~/work/obsidian-vault/`** — Obsidian vault (wiki, worklog, plans).
- **`/srv/docker/deepthought/`** — Docker Compose service definitions for this machine. All services live here — no exceptions.

## System Overview

| Component | Details |
|-----------|---------|
| OS | Ubuntu 22.04.5 LTS, running kernel **5.15.0-190-generic**. NVIDIA **580.178.04** — kernel module and userspace match, `nvidia-smi` healthy, CUDA available. Fixed 2026-09-14 by reloading the modules (no reboot). NVIDIA packages are now held back from unattended-upgrades and `homelab-health gpu` checks for the mismatch — see the vault runbook *NVIDIA Driver Mismatch (Deepthought)*. |
| Hostname | deepthought |
| CPU | Intel Core i9 |
| RAM | 32 GB (31 GiB usable) + ~23 GB swap (15.5 GB zram + 8 GB file) |
| GPU | NVIDIA RTX 4070 Laptop (8 GB VRAM) — driver 580, CUDA 13.0 |
| Internal SSD | 953.9 GB NVMe — root LV expanded to 950.82 GiB |
| External SSD | 3.6 TB NVMe (exFAT) — personal data (Photos/, Becky/) — do not touch |
| Ethernet | enp153s0 — 192.168.42.150/24 |
| Tailscale | `deepthought.batfish-pride.ts.net` — **100.78.161.123** (installed 2026-10-10, v1.104.1, official apt repo, `tailscaled` system service, no `--ssh`/exit-node). HTTPS certificates enabled for the tailnet 2026-10-11; `tailscale serve` proxies `https://deepthought.batfish-pride.ts.net/` to the Vault Graph server (:8797). Published Docker ports (Neo4j :7474, Syncthing :8384, …) answer on this address too. |

## Running Services

All services are defined in `/srv/docker/deepthought/` and tracked in git.

| Service | Port | Compose path | Status |
|---------|------|--------------|--------|
| Ollama | :11434 | systemd (not Docker) | running |
| TTS | :8000 | `/srv/docker/deepthought/tts/` | running |
| n8n | :5678 | `/srv/docker/deepthought/n8n/` | running (image `n8n-ytdlp:latest`, locally built) |
| Navidrome | :4533 | `/srv/docker/deepthought/navidrome/` | running |
| Snapcast + MPD + myMPD | :1704/:8080 | `/srv/docker/deepthought/snapcast/` | running |
| Glances | :61208 | `/srv/docker/deepthought/glances/` | running |
| Docker socket proxy | :2375 | `/srv/docker/deepthought/socket-proxy/` | running |
| node-exporter | :9100 | `/srv/docker/deepthought/monitoring-agents/` | running — scraped by Prometheus on Trillian. **UFW must allow 9100/tcp from 192.168.42.189**; without that rule Deepthought reports as `HostDown` while being perfectly healthy, and every host-level alert for this machine (disk, CPU, memory) is silently dead. That was the state for 10 days until 2026-08-23. |
| Agentic Pipeline | :18800 | `/srv/docker/deepthought/agentic-pipeline/` | **NOT running** — paused 2026-10-16 in the resource cleanup (no caller found). Its 03:00 indexer cron line is commented out. Start with `docker compose up -d` and uncomment the cron. |
| ComfyUI | :8188 | **user** systemd unit `comfyui.service` (not Docker) | running — binds `127.0.0.1` only, so it will not show in a `ss -ltn` scan for LAN ports. Manage with `systemctl --user status comfyui`. **Holds VRAM while idle** — measured 5,056 MiB on 2026-08-19, contradicting its own unit comment; `gpu-exclusive on` stops it. |
| gpu-moded | :8485 | **user** systemd unit `gpu-mode.service` (not Docker) | running — GPU-exclusive mode toggle. Binds `127.0.0.1` **and** `192.168.42.150`; UFW allows 8485/tcp from Trillian only. Routes: `GET /api/status`, `POST /api/mode`, `POST /api/model`. Scripts live in `~/work/gpu-mode/`, symlinked into `~/bin` and `~/.config/systemd/user/`. |
| Syncthing | :8384 (UI), :22000 (sync) | `/srv/docker/deepthought/syncthing/` | running — phone → Marvin. Writes into `/marvin/Pictures/Phone Drop` over NFS; index DB stays on local disk. `network_mode: host` because local discovery is broadcast-based and cannot work on a bridge. UFW allows 8384/22000/21027 from the LAN only. Also syncs three **Obsidian vaults** to the phone (send-receive, trashcan versioning 14 d, added 2026-10-10): folder IDs `kink-rag`, `obsidian-vault`, `obsidian-ai` = `~/work/obsidian-kink-rag`, `~/work/obsidian-vault`, `~/work/obsidian-ai`, bind-mounted at `/var/syncthing/<id>`. Each vault's `.stignore` keeps `.git` and caches off the phone (kink-rag also pipeline/staging/book-queue/`16-Transcripts`; obsidian-ai also `gpud/`). Each has a `Sync.md` (git-excluded) whose "Sync now" checkbox is handled by `~/bin/vault-sync-on-demand.py <vault>` — commit, rebase, push, confirm via ls-remote, write result, untick. Run every minute per vault by **user** timers `vault-sync-on-demand@<dir>.timer` (`obsidian-kink-rag`, `obsidian-vault`, `obsidian-ai`; template units in `~/.config/systemd/user/`), a no-op unless the box is ticked. Logs: `journalctl --user -u 'vault-sync-on-demand@*'`. The personal vault is deliberately **not** shared (stays Anjie-only). |
| homelab-notify + ntfy | :8490 (API), :8491 (ntfy) | `/srv/docker/deepthought/homelab-notify/` | running since 2026-09-29 — job notifications: phone push via ntfy (topic `homelab`) + Nest Hub speech via HA (`192.168.42.142:8123`, hubs `media_player.basement_bedroom_hub` + `basement_display`). Config `/etc/homelab-notify/config.ini`, secrets `/etc/homelab-notify.env` (mode 600). CLI `hn` symlinked in `/usr/local/bin`. **Code is bind-mounted from the worktree `~/worktrees/homelab-notify/homelab-notify`** (branch `claude/project-thread-ohb0bm`, not yet merged) — after merge, re-run `sudo ~/work/homelab-notify/install.sh` to repoint `HOMELAB_NOTIFY_SRC`, then remove the worktree. Both ports are published and reachable from the LAN (Docker bypasses UFW); no auth. |
| FetLife refresh | — | **user** systemd `fetlife-refresh.timer` / `.service` (`~/.config/systemd/user/`, not Docker) | running — timer every 10 min (paused 2026-10-22, re-enabled 2026-10-23 at Stephen's request). Liked photos go to `/marvin/Videos/Porn/FetLife Liked`, which Stash on Trillian shows as gallery **FetLife Liked Photos** (id 11, folder-based). Since 2026-10-25 (Stephen's choice) machine-group (390) threads also follow their picture links — FetLife picture pages and outside image files, one picture each, never onward (`FETLIFE_FOLLOW_PICTURES=all` in the unit); comment pages are fetched too, and avatars are never kept. Code runs from the worktree `~/work/fetlife-refresh-wt` (branch `claude/fetlife-refresh`); half-fetched threads wait in `~/.local/state/fetlife-refresh/partial/`. Re-fetch a saved thread: `fetlife_refresh.py queue <url> --force`; first look (opening page only): `--survey`. Daily page cap raised to 40 (`FETLIFE_FETCH_PER_DAY=40`, Stephen 2026-10-25), still 2 pages an hour. Pause: `systemctl --user disable --now fetlife-refresh.timer`. If `list-timers` shows NEXT `n/a` after enabling, start the service once to arm `OnUnitActiveSec`. |
| Liked-tag review | :8798 (127.0.0.1 only) | **user** systemd unit `liked-tagger.service` (not Docker), code `~/work/liked-tagger/` | running since 2026-10-25 — voice-driven swipe page for tagging the liked FetLife photos in Stash. Open at **`https://deepthought.batfish-pride.ts.net/tags/`** (`tailscale serve --set-path /tags`, tailnet only, next to the Vault Graph's `/`). Writes tags straight to Stash on Trillian; every change logged in `decisions.jsonl` and undo-able. Proposals come from `propose.py` (MiniCPM-V 4.5 on Ollama, ~35 s/photo, newest photos first), run by user timer `liked-tagger-propose.timer` 15 min after each run ends. Ratings and "Rejected photo" (nothing deleted) are written to Stash too. Remove the path with `sudo tailscale serve --set-path /tags off`. |
| Lecturn library batch | — | **user** systemd unit `lecturn-library.service` (not Docker) | running since 2026-10-25 20:38 (enabled, verified 2026-10-26); started by hand, not on a timer: `systemctl --user start lecturn-library`. Runs `~/work/lecturn/bin/lecturn batch` over the Marvin class folders and commits to `~/work/obsidian-kink-rag` after each group (`~/lecturn-pilot/commit-vault.sh`). **The real DB is `~/lecturn-pilot/lecturn.sqlite3`**, not `~/work/lecturn/data/` (which holds 2 test videos). Manual DB-backed lecturn commands need the unit's `LECTURN__PATHS__*` env (`systemctl --user cat lecturn-library`). Repointed 2026-10-10 from the `~/wt/qau1rt` worktree to `~/work/lecturn` (backup `lecturn-library.service.bak-2026-10-10`); `~/work/lecturn/.venv` has the ml + claude extras. |
| Neo4j (kink-rag graph) | :7474 (Browser), :7687 (Bolt) | **not in `/srv/docker/deepthought/`**: compose file is `99-Meta/graph/neo4j/docker-compose.yml` in obsidian-kink-rag, started from the worktree `~/work/kink-graph-pr` (branch `claude/lightrag-hybrid`), project `neo4j`, container `neo4j-neo4j-1`, volume `neo4j_neo4j-data` | running since 2026-10-10. Holds the vault graph (`sync.py`) and the LightRAG pilot graphs (labels `lightrag_hybrid`, `_haiku`, `_opus`, `_local`). Password in `~/lightrag-kink/neo4j.env` (mode 600); load with `set -a; . ~/lightrag-kink/neo4j.env; set +a`. Changing `NEO4J_PASSWORD` in compose does **not** change it once the volume exists; use `ALTER CURRENT USER` via `cypher-shell -d system`. **Both ports are published on 0.0.0.0** (LAN and tailnet), password-only. LightRAG venv and data: `~/lightrag-kink/` (`.venv`, per-workspace stores, `usage-*.jsonl`). |
| Vault Graph server | :8797 | **user** systemd unit `vault-graph.service` (not Docker), code `99-Meta/graph/viewer/serve.py` in the same worktree | running since 2026-10-10. Serves `~/lightrag-kink/viewer/graph-*.json` (written by `export.py`) to the Godot app `vault_graph` (native-frontend-framework, branch `vault-graph`), and that app's web build + APK at `/app/` (from `~/lightrag-kink/viewer/app/`). **Open it at `https://deepthought.batfish-pride.ts.net/app/`** (any tailnet device): tailnet HTTPS certificates enabled and `tailscale serve --bg --https=443 http://127.0.0.1:8797` set up 2026-10-11 (tailnet only, not Funnel; persists across reboots; `tailscale serve status`, undo with `sudo tailscale serve --https=443 off`). The web build needs HTTPS off localhost (Godot secure-context rule). Binds **127.0.0.1 and 100.78.161.123 only**, not the LAN, because it has no auth. After the obsidian-kink-rag branch merges, repoint `WorkingDirectory` at `~/work/obsidian-kink-rag`. |

### Monitoring agents

`node-exporter` runs with `--collector.textfile.directory=/textfile`, bound to
`/srv/docker/deepthought/monitoring-agents/node-exporter-textfile`. Anything
dropping a `*.prom` file there is scraped by Prometheus on Trillian.

Currently one producer: `homelab-health-textfile` (cron, every 5 min) writes
`homelab_health.prom` — Marvin's drive health, temperatures, bad-sector counts
and volume utilisation over SNMPv3. This is the only path by which NAS hardware
faults reach alerting; before 2026-08-23 they reached nothing at all. The alert
rules live on Trillian in
`/srv/docker/trillian/monitoring/prometheus/alerts/infrastructure.yml`
(group `nas-hardware`), and `MarvinHealthStale` fires if the cron stops.

**Whisper ASR was decommissioned 2026-05-12** (commit `808b710`, "remove: whisper ASR
service from deepthought"). The compose directory no longer exists — do not expect
anything on :9000. The two stale images (`onerahmet/openai-whisper-asr-webservice`
`latest-gpu` + `v1.6.0-gpu`, 45 GB) have since been deleted — verified absent
2026-08-27, nothing to reclaim there now.

**Retired 2026-10-16 (resource cleanup, Stephen's swipe choices):** Open WebUI + SearXNG and the `~/bin/vault-sync` cron that fed it (chat DB archived; the 26 GB vector DB was dropped), LibreChat (5 containers),
openclaw + its vault/projects/n8n MCP sidecars, JobSpy, escapes (nginx), Hive, SillyTavern
(`~/work/roleplay-stack`, repo kept), cadvisor (removed from `monitoring-agents`), the
ComfyUI-next checkout, the pornbot n8n feeds, and the debt-tracker sync cron. Compose dirs
and named volumes are archived in `~/archive/retired-2026-10-16/` (mode 600: the openclaw
archive holds its `.env`). The nightly backup no longer tries LibreChat or openclaw.

This table lists the primary services only — the host runs 16 containers in total
(2026-10-26), including multi-scrobbler, node-exporter and promtail. searxng is gone.
Every app with a page or port, on both hosts, is listed in `~/work/homelab-services/services.yaml`
(on Trillian); `python3 check.py` there reports drift on this host over ssh.

### Qwen-Image 2.1 weights — DELETED 2026-09-23

The four files from `abenzerps/Qwen-Image-2.1-Uncensored-GGUF` (~20 GB) were
fetched for the bake-off and **deleted the same day** once the comparison was
done. Disk went 285 GB → 304 GB free. Nothing referenced them: Qwen-Image is not
in gpud's model registry, and the production ComfyUI cannot load them anyway.

Do not expect anything Qwen-Image under `~/ComfyUI/models/`. The
`qwen_3_4b_fp8_mixed.safetensors` still in `text_encoders/` is **z-image's**
encoder and is unrelated — leave it alone.

To bring them back (~4 min at ~65 MB/s), and for the run that would need them,
see `obsidian-ai/art-tools/docs/CRYPTID_QWEN_RUN.md`. Fetch **Q4_K_M only**;
the Q6_K quant was downloaded once and never tested.

### Ollama Models

**Ollama 0.32.14** (upgraded from 0.20.2 on 2026-08-19 — the `qwen35` arch would not
load on the old bundled llama.cpp; old binary kept at `/usr/local/bin/ollama.0.20.2.bak`).
`OLLAMA_FLASH_ATTENTION=1` via `/etc/systemd/system/ollama.service.d/flash-attention.conf`.

**`OLLAMA_KV_CACHE_TYPE=q8_0`** via `/etc/systemd/system/ollama.service.d/kv-cache.conf`
(set 2026-08-27). Halves K/V-cache VRAM against the f16 default. Verified working
rather than silently falling back — `chat:latest` at 32768 ctx went **5041 -> 4661 MiB**
(nvidia-smi), and throughput was unchanged at **68.4 tok/s**. It requires flash
attention, which is already on; without it the setting is ignored.

The headroom this buys is the real point: `chat` now runs **131072 ctx at 100% on
GPU** (5.93 GB). Under f16 the measured ceiling was 65536 — see the benchmark table
below, whose figures all predate q8_0 and are therefore conservative. The baked
`num_ctx` is still 32768; raising it is a deliberate trade against ComfyUI and
`big:latest`, both of which want the whole card.

> [!warning] The systemd drop-ins are not in any git repo
> `/etc/systemd/system/ollama.service.d/` (`flash-attention.conf`, `override.conf`,
> `kv-cache.conf`) is unmanaged. These four env vars — flash attention, KV cache
> type, `OLLAMA_KEEP_ALIVE=15m`, `OLLAMA_MAX_LOADED_MODELS=2` — exist only on this
> host and would be lost in a rebuild.

**25 models, ~91 GB on disk** (`/usr/share/ollama/.ollama/models`) — verified 2026-10-16,
after the cleanup deleted 13 models (~93 GB) that had not loaded in 30 days: the two
`qwen3-vl-abliterated:30b-a3b` variants, `create-long` / `gemma3-abliterated:12b`, the
rejected 27B quants, `llava:13b`, `gemma-4-abliterated:e2b`, `think-open` /
`deepseek-r1-abliterated:8b`, `mxbai-embed-large`, `jina-embeddings-v5` and
`nomic-embed-text-v2-moe`. The per-model lists further down are updated to match. Regenerate with `ollama list` or
`curl -s localhost:11434/api/tags`. Only 8 GB of VRAM, so anything above ~8 GB spills to
CPU and runs slowly. `OLLAMA_MAX_LOADED_MODELS=2` (see below) and
`OLLAMA_KEEP_ALIVE=15m`.

**Task aliases** — local tags pointing at identical weights, used by service configs
so the underlying model can be swapped without touching every `.env`:

| Alias | Resolves to | Size |
|-------|-------------|------|
| `chat` | **`qwen3.5:4b`** (repointed 2026-08-21; `num_ctx` 32768 baked in) | 3.4 GB |
| `think` | `deepseek-r1:8b` | 5.2 GB |
| `create-open` | `huihui_ai/qwen3-abliterated:8b` | 5.0 GB |
| `write` | `gemma3:12b` | 8.1 GB |
| `big` | `hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ2_S` (27B, `num_gpu` 48, `num_ctx` 16384) | 9.3 GB |

`big:latest` runs at **10.4 tok/s** and is only usable with `gpu-exclusive on` —
it needs essentially the whole 8 GB card, and **must never be paired with an
embedding model**: it is left with 44 MiB and CUDA-OOMs unpredictably (see
`~/work/gpu-mode/docs/quant-bakeoff-2026-08-20.md`). `OLLAMA_MAX_LOADED_MODELS`
is now **2**, so `qwen3.5:9b` + `nomic-embed-text` co-reside and Open WebUI's
memory/search/file features work without evicting the chat model. See the vault's [[GPU Mode Daemon]] note.

### Benchmarked models (2026-08-20)

Not aliases — real models, measured across seven suites. Full results and method:
`~/work/gpu-mode/docs/bench-results-2026-08-20.md`.

| Model | Size | Max ctx fully on GPU | tok/s @4096 | Notes |
|---|---|---|---|---|
| `qwen3.5:4b` | 3.4 GB | **65536** | **66.9** | benchmark winner; only model that never spills |
| `qwen3.5:9b` | 6.6 GB | 16384 | 41.9 | better at code fix/feature and summarisation |
| `chat` (was `qwen3:8b`) | 5.2 GB | **4096** | 43.9 | the former default — see the gaps below |

**`chat:latest` has two hard capability gaps**, not score deficits: it **cannot process
images at all** (`HTTP 400: model does not support multimodal requests`) and it **never
produced a unified diff** in six attempts. It also spills to CPU at 16384 and halves to
19.2 tok/s — so anything run above 4k context today is already paying that penalty. It
does keep one genuine advantage: arithmetic, 0.667 vs 0.4 / 0.333 for the challengers.

**`chat` was repointed to `qwen3.5:4b` on 2026-08-21** with `num_ctx` **32768** baked in
(Modelfile: `~/models/modelfiles/chat.Modelfile`). Verified after the swap: 32768 context
**100% on GPU**, 69 tok/s, and `nomic-embed-text` co-resident *also* 100% on GPU with
2255 MiB still free. The model it replaced spilled to CPU at 16384 and halved to 19 tok/s —
so this is an 8× context increase and a throughput increase at once.

Sampling comes from qwen3.5:4b's own Modelfile (temperature 1, top_k 20, top_p 0.95,
presence_penalty 1.5), not the old alias's temperature 0.6 — the model author's values.

Rollback is one command; `qwen3:8b` is still installed under its own name:

```bash
ollama create chat -f <(echo 'FROM qwen3:8b')
```

> [!note] Thinking mode is not yet measured
> The first think-on run measured truncation, not reasoning — an 800-token budget was
> consumed entirely by the thinking block. Re-running 2026-08-20 with a measured 3700
> budget. Every figure above is **thinking-off**.

`create-open:latest` is the `TEXT_MODEL` in `/srv/docker/deepthought/agentic-pipeline/.env`.
(n8n sets no model vars — its workflows pick models per-node.)

**Text / reasoning:** `qwen3:8b`, `qwen3:30b-a3b` (18.6 GB MoE), `gemma3:12b`,
`deepseek-r1:8b`, `qwen3-jake:8b`.

**Vision:** `huihui_ai/qwen3-vl-abliterated:8b`, `huihui_ai/qwen2.5-vl-abliterated:7b`,
`minicpm-v:8b`, `openbmb/minicpm-v4.5`,
`huihui_ai/granite3.2-vision-abliterated`. `minicpm-v:8b` is the configured
`VISION_MODEL`.

**Embeddings:** `nomic-embed-text` (274 MB — used by the RAG indexer; **2048-token
context**, which is why the indexer must keep chunks under ~1400 chars),
`qwen3-embedding:4b`, `qwen3-embedding:8b`, `bge-m3` and `embeddinggemma` (kink-rag-hybrid / LightRAG).

**Special:** `hf.co/mradermacher/DanTagGen-gamma-GGUF:Q8_0` — booru tag generation
for image prompting.

Uncensored/abliterated variants are the `huihui_ai/*` line. The older
`dolphin-*`, `llama2-uncensored` and `wizard-vicuna-uncensored` models named in
earlier revisions of this file are **no longer installed**.

## NAS — marvin

Marvin is a Synology NAS at **192.168.42.186** (OUI 00:11:32). NFS share: `/volume1/Marvin`.

On Deepthought, Marvin is mounted at `/mnt/marvin/photos` via systemd unit `mnt-marvin-photos.mount`.

Relevant subdirectories (paths relative to the NFS mount root):
- `Music & Audio/Music` — primary music library
- `Music & Audio/DJ Mixes` — DJ mix files
- `Pictures/Photos/` — organized photo library (by year)
- `Pictures/Photo Intake/Staging/` — camera ingest staging area

## Sony A7 IV Photo Ingest

Automated USB ingest pipeline installed 2026-05-11. Camera plugs in → udev triggers → rsync to Marvin.

| Item | Value |
|------|-------|
| Camera USB ID | 054c:0da5 (ILCE-7M4) |
| Block devices | sda1 (CF 149 GB), sdb1 (SD 238 GB), sdc1 (internal 64 MB) |
| udev rule | `/etc/udev/rules.d/90-sony-a7iv-ingest.rules` |
| Systemd service | `sony-a7iv-ingest@.service` (template, udev-triggered) |
| Marvin mount | `mnt-marvin-photos.mount` → `/mnt/marvin/photos` |
| Ingest scripts | `/opt/photo-ingest/` |
| Log | `/var/log/sony-a7iv-ingest.log` |
| Env/config | `/etc/photo-ingest.env` |
| Destination on Marvin | `Pictures/Photos/YYYY/YYYY-MM-DD/` — named for the **capture** date, not the ingest date (changed 2026-09-10) |
| Staging on Marvin | `Pictures/Photo Intake/Staging/.staging/<ingest-id>/` (transient) |
| Dedupe index | `Pictures/Photos/.ingest-index/` — `capture.idx` (41,463 identities) + `sha256.idx` |
| Notifications | via homelab-notify (`hn`, source `photo-ingest`) → phone push + Nest Hub speech; installed 2026-09-29 |
| Immich | v3.0.2 on **Trillian** at `192.168.42.189:2283` — external library, scanned after each ingest |

Watch a live ingest: `sudo journalctl -u 'sony-a7iv-ingest@*' -f`

Ingests are deduped against `capture.idx` before anything is transferred, so
re-plugging an unformatted card copies nothing. **Re-seed the index after any manual
reorganisation of `Pictures/Photos/`**, or the next ingest treats the whole card as new:

```bash
sudo python3 /opt/photo-ingest/ingest-dedupe.py backfill \
  --library "/mnt/marvin/photos/Pictures/Photos" \
  --index   "/mnt/marvin/photos/Pictures/Photos/.ingest-index"
```

## Personal Vault

The personal Obsidian vault (daily notes, brand, personal info, accounts) is **permitted on Anjie, Deepthought and Trillian**. The ciphertext repo is at `~/work/obsidian-personal-enc/` (gocryptfs-encrypted). Mount the plaintext at `~/work/obsidian-personal/` using the passfile at `~/.config/gocryptfs/personal-vault.pass` (must be provisioned manually). Auto-sync commits and pushes ciphertext every 5 minutes via cron (`~/bin/sync-personal-vault.sh`). Trillian is a trusted host for all data, including plaintext personal content (Stephen, 2026-10-11). Zaphod is decommissioned.

## Claude Remote Control

`claude-remote-control.service` (systemd user unit, enabled, linger on) runs
`claude remote-control` from `~/work` so Deepthought's sessions appear in the Claude app
(session names prefixed `deepthought`). Unit: `~/.config/systemd/user/claude-remote-control.service`,
tracked in the home repo. `Restart=always`: if the claude.ai login lapses it exits
and retries every 10 s, resuming on its own once you run `claude auth login`.
Diagnose with `journalctl --user -u claude-remote-control -n 20`. Needs `~/work`
trusted in `~/.claude.json` (`hasTrustDialogAccepted`). Installed 2026-10-03.

## Critical Constraints

- **Always ask before rebooting the machine.**
- **Do NOT format or modify the external SSD** (`nvme1n1p2`) — it contains personal data (Photos/, Becky/, Becky.zip). Explicit confirmation required for any partition changes.
- Secure Boot is disabled in BIOS to allow nvidia-dkms-580 to load — do not re-enable it.

## Wrap-Up Config

- Worklog file: `~/work/obsidian-vault/70-Homelab/Operations & Runbooks/Worklog.md`
- Worklog git repo: `~/work/obsidian-vault/`

## Pending Setup Tasks

See the To Do section of `70-Homelab/Servers/Deepthought — AI Server State.md` in the vault for the authoritative current list. As of last update:

- [ ] Decide on external SSD usage (3.6 TB — has personal data, plan partitioning)
- [ ] Set up automatic startup (systemd services)
- [x] Tailscale for remote access (done 2026-10-10)
- [x] Reboot to apply latest kernel (done 2026-08-12 → 5.15.0-187)

## Common Commands

```bash
# Check GPU
nvidia-smi

# Check storage
df -h /
sudo vgdisplay && sudo lvdisplay

# Check network
ip link show
nmcli device status

# Check swap
zramctl
cat /proc/swaps

# Manage Docker services
cd /srv/docker/deepthought/<service> && docker compose up -d
docker compose ps

# Photo ingest
sudo journalctl -u 'sony-a7iv-ingest@*' -f
sudo tail -f /var/log/sony-a7iv-ingest.log

# Run setup script
sudo bash /home/scon/ai-server-setup.sh
```
