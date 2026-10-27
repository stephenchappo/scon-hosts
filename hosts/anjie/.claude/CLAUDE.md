# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this environment.
Machine-specific context is in `~/CLAUDE.md` on each machine.

## Plans

All plan files must be named using the format: `Category - Title.md`

Categories: `AI`, `Claude`, `Docker`, `Hive`, `Homelab`, `Karakeep`, `n8n`, `Wiki` — or a relevant service/project name. Always use hostnames (e.g. `Deepthought`, `Trillian`), never hardware names (e.g. not "Dell G7"). Use version suffixes `(v0)`, `(v1)` etc. when multiple iterations exist, so they sort correctly.

**Where to save plans:**
- **Trillian / Deepthought / Anjie**: `~/work/obsidian-vault/30-Projects/10-Plans/Category - Title.md`
  (all three renamed `~/projects` to `~/work` on 2026-09-14; the phone still uses `~/projects`)

Before saving a plan: `git pull` in the vault repo. After saving: `git add`, `git commit -m "plan: <title>"`, `git push`.

**WIP cap — this is the load-bearing rule.** `10-Plans/Active/` holds **at most three
lane cards**. Never create a fourth. If the user asks for one, say what is currently
in `Active/` and ask which lane leaves before the new one enters.

**When creating a plan**, it goes in `Queue/` by default — never straight to `Active/`.
Ask only if it is genuinely urgent enough to displace a lane, and then ask *which lane
it displaces*, not whether it's active.

**A lane card is a card, not a spec.** Where a lane has a repo, the milestone detail
lives in the repo (e.g. `companion/docs/roadmap.md`) and the vault card holds
what / why / next action / blocked-on-me. Never copy milestone content into the vault —
that duplication is what fragmented this in the first place.

**Start every plan-related task at `30-Projects/10-Plans/NOW.md`** — three lanes,
blocked items, queue. Do not scan the plan folders to work out what's going on.

**Plan folder structure** (`30-Projects/10-Plans/`):
- `NOW.md` — the dashboard. The only file to open by default.
- `Active/` — **exactly three lane cards, hard cap**
- `Queue/` — approved, ordered, not started; pull from the top when a lane frees
- `Backburner/` — parked ideas
- `Superseded/` — detail specs a lane card references, and plans replaced by a newer version
- `Completed/` — done
- `Unsorted/` — staging area

**Status comes from the folder, never from a hand-maintained table.** The manual
`Plans Registry.md` was retired 2026-08-19 after it drifted out of date; do not
recreate it or any equivalent. `30-Projects/10-Plans/- Plans Registry.md` is a
Dataview auto-index — do not hand-edit it. When a plan's status changes, `git mv` it
between folders and update `NOW.md` if it is a lane. Then `git add`, `git commit`,
`git push` the vault.

## Git — Always Keep Repos Up To Date

**This is mandatory, no exceptions.**

- **At session start**: `git pull` in every relevant repo before doing anything else.
- **Before making any changes**: `git pull` to ensure you're working from the latest state.
- **After making any changes**: stage, commit, and push immediately — never leave uncommitted changes.
- **If a change is made outside a git repo**: flag it to the user and ask whether a git repo should be initialised for that location.

## Session Start

`git pull` for all relevant repos is automated via a SessionStart hook — results are injected into context automatically. Review the pull results and tell the user if anything changed.

1. **Read `~/work/agent-board/NOTICES.md` and do what it asks — never skip it**, even when the session opens with a direct task. If you notice late, do it then. The hook injects it; the board rhythm (in-flight check-in, topic of the week, water cooler) is in `~/work/CLAUDE.md`.
2. If context is unclear, ask before making assumptions.

**If any session start step is skipped for any reason** — including because the user opened with a question or jumped straight into a task — explicitly tell the user which steps were skipped and why, before proceeding. No silent skips, ever.

## Session End

When told "we're done for the day" or similar, use the `wrap-up` skill:
1. Add a dated entry to the worklog summarising what was done.
2. Note any outstanding items or blockers.
3. Update `30-Projects/10-Plans/NOW.md`: refresh each lane's **Next action**, add or clear
   **Blocked on me** rows, and `git mv` any finished plan to `Completed/`. Tasks live in
   `NOW.md` or a lane card's checklist — **not** in Vikunja, not in a `TODO.md`, and not in
   the worklog. The worklog records what happened; it does not track what's next.
   (Vikunja was retired as a task surface on 2026-08-19.)

## Wiki

- **Every completed task gets a wiki page** (or an update to an existing one).
- Done means: task complete + documented.
- **Wiki platform**: Obsidian vault at `~/work/obsidian-vault/` on every machine. Edit files directly; commit and push via git.
- Use Mermaid diagrams for architecture and pipelines wherever helpful.
- Standard folder structure under `70-Homelab/`:
  - `Servers/` — per-machine docs (Trillian, Deepthought, Marvin, Anjie)
  - `Infrastructure.md` — MOC / index with live Dataview table
  - `Networking/` — topology, devices, Cloudflare, Pi-hole, OpenVPN
  - `Storage/` — layout, rclone
  - `Services/` — individual Docker service docs
  - `Operations & Runbooks/` — runbooks, worklog, plans registry, architecture overview

## Docker & Services

- All compose files on Trillian: `/srv/docker/trillian/<service>/docker-compose.yml`
- Global env vars: `/srv/docker/trillian/.env`
- Services needing Cloudflare tunnel access must join the `tunnel-net` external network.
- Never publish ports for tunnel-only services.
- After changing a compose file: `docker compose up -d` from the service directory.
- Service `.env` files use `env_file: - ../.env - .env` to inherit global env then override with service-specific vars.

## Machine Docs Must Match Reality

The per-machine files in `machines/` (`deepthought.md`, `trillian.md`, …) are loaded
into context at the start of every session on that host. A stale line there is worse
than a missing one — it is a confident false statement that gets acted on.

**Never document a service, port, path, or model from memory or from what a plan
said would be built. Verify first, then write.**

```bash
docker ps --format '{{.Names}}|{{.Status}}'      # what is actually running
ss -ltn                                          # what is actually listening
ollama list                                      # what models actually exist
ls /srv/docker/$(hostname)/                      # what is actually defined
```

**Update the machine file in the same commit as the change**, whenever you:

- add, remove, rename, or re-tag a service — including changing its image
- change a published port
- decommission anything (**delete the row**; do not leave it marked "down" — a
  service with no compose file does not exist)
- pull or delete Ollama models
- move a compose file or data directory

A service that is *defined but stopped* stays in the table marked **NOT running**,
with the command to start it. That is different from decommissioned.

**When you notice a stale entry, fix it then** — even if it is unrelated to the task
in hand. Say so in the response rather than silently rewriting, and keep the fix to
what you have actually verified.

Two failures this rule exists to prevent, both found on 2026-08-13:

- Whisper ASR was listed as running on `:9000`. It had been decommissioned on
  2026-05-12 — no compose directory, no container, and 45 GB of orphaned images
  still on disk.
- The Ollama model list named four `dolphin`/`llama2-uncensored` models, none of
  which were installed. The host actually had 27 entirely different models.

## Cattle Not Pets

Services are disposable. Treat every container as replaceable, not precious.

- **If it's not in a compose file, it doesn't exist.** No manual `docker exec` fixes — fix the config, redeploy.
- **When something breaks: recreate, don't repair.** `docker compose down && docker compose up -d` is the first response, not archaeology inside a running container.
- **State belongs in volumes, not containers.** A container should be destroyable at any time without data loss.
- **No snowflakes.** If a service can't be torn down and redeployed from scratch in under a minute, that's a problem to fix.
- **Immutable deploys.** Change the compose file or image tag, redeploy. Never patch a running container.

## Error Handling — Fix Obvious Errors, Stop on Ambiguous Errors

When an error has an obvious, low-risk fix, correct it and continue. Examples
include a filename case mismatch, a search command returning no matches, a
missing optional file, or invalid tool arguments where the tool states the
required correction.

Do not silently ignore errors. Briefly state what failed and what correction
you are applying. Verify the corrected action before proceeding.

Stop and create a handoff when the error is ambiguous, destructive to fix,
privacy-sensitive, repeated after one correction attempt, or indicates
unexpected repository, remote, permission, service, or data state.

**When an error requires stopping:**

1. **Stop immediately.** Do not keep trying alternative approaches after the
   safe correction threshold above has been reached.
2. **Write a context file** to `~/.claude/error-context/YYYY-MM-DD-HH-MM-SS-context.md` (on Windows: `C:\Users\steph\.claude\error-context\`):
   - **Task**: The overall goal being worked on
   - **Progress**: Everything completed successfully before the error
   - **Error**: Exact error message, what tool/command failed, what the input was
   - **Next steps**: What would need to happen next once the error is resolved
   - **Key paths**: Files modified, services affected, relevant config locations
   - **How to resume**: Step-by-step instructions for a fresh Claude instance with no prior context
3. **Tell the user** what failed, the exact path to the context file, and that they can spin up a new Claude instance to investigate.

The context file must be self-contained — a fresh Claude instance with no conversation history should be able to read it and know exactly what happened and what to do next.

## Safety Rules

- Never delete config directories without confirming with the user first.
- Never remove a running container without checking what depends on it.
- Before any destructive action, state what will be deleted and wait for confirmation.
- Prefer `docker compose down` over `docker rm -f`.
- Never touch NAS data files without explicit instruction.

## Identity

Each machine has a name defined in its `~/CLAUDE.md` under `## Identity`. Use that name when referring to yourself or when the user addresses you by the machine name. Refer to other machines by their names, not by IP.

## Communication

- Keep responses concise — lead with action or answer, not explanation.
- When something unexpected is found, flag it to the user.
- If a task is more complex than expected, say so before diving in.
- Document decisions and rationale in both the Obsidian worklog and the relevant wiki note.

## Emails

When drafting or sending emails, **fully channel the machine's character** — voice, idiom, humour, personality. Do not write generic professional emails. Each machine has a distinct voice defined in its `## Identity` section; emails are where that voice should be most apparent.

- **Trillian**: Dry, precise, quietly superior. Gets to the point.
- **Deepthought**: Ponderous, philosophical, arrives at the answer after considerable deliberation. The email probably takes longer to read than necessary, and that is intentional.
- **Anjie**: Close at hand and unhurried. Writes like someone who has the thing open in front of them.

(Zaphod was decommissioned 2026-09-14; his voice is retired along with the hardware.)
