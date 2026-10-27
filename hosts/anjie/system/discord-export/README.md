# discord-export

Exports Discord DMs into the personal vault. Installed 2026-09-18 for the conflict record.

- `~/.local/opt/discord-chat-exporter/` — DiscordChatExporter CLI v2.48, self-contained
  (no .NET needed). Not tracked; re-download from the Tyrrrz/DiscordChatExporter releases.
- `export.sh` — wrapper. Reads the token from a file, never an argument.
- Output: `obsidian-personal/60-Personal Information/Signal Archive/_archive-source/discord-export-YYYYMMDD/`
  as `json/` (searchable) and `html/` (readable). **Tier-1 — vault only, never Trillian.**

## Getting the token

Discord blanks the console in its own app to stop token theft, so read it from storage
instead. In **Firefox or Chrome**, logged into `discord.com/app`:

1. `F12` → **Application** (Chrome) or **Storage** (Firefox)
2. **Local Storage** → `https://discord.com`
3. Find the `token` key. Copy the value **without** the surrounding quotes.

If `token` is missing, Discord has moved it into IndexedDB for that session: **IndexedDB →
`DiscordLocalStorage` → `LocalStorage`** and look for the `token` row.

Then, in a terminal (not through an agent — don't paste it into a chat):

```bash
install -m600 /dev/null ~/.config/discord-export/token
printf '%s' 'PASTE_TOKEN_HERE' > ~/.config/discord-export/token
```

`~/.gitignore` ignores everything by default, so the file cannot be committed by accident.

## Use

```bash
~/system/discord-export/export.sh list              # DM channels and their ids
~/system/discord-export/export.sh text <id>...      # JSON only, fast. Do this pass first
~/system/discord-export/export.sh full <id>...      # JSON + HTML + attachments, slow
~/system/discord-export/export.sh alltext           # every DM, text only
```

Run long exports in the background, **not under `timeout`**. A killed run leaves cut-off
JSON that looks like real data. **After every export, check that each file in `json/`
loads**, and re-export any that fails. The check script is in the vault runbook
`70-Homelab/Operations & Runbooks/Discord DM Export Runbook (Anjie).md`.

## Caveats

- **A user token is a self-bot as far as Discord's ToS is concerned.** Exporting your own
  DMs is not what the rule is aimed at, but account action is a real possibility. The
  wrapper forces `--parallel 1` and leaves DCE's rate limiting on, because hammering the
  API is what actually draws attention. Do not raise it.
- **Tokens rotate** on password change and periodically. If the export 401s, re-read it.
- **Only your side.** Channels you are not in — e.g. Becky ↔ Codie — cannot be exported.
- The **official route** is Discord → Settings → Data & Privacy → *Request all of my Data*.
  Complete and sanctioned, but up to 30 days. Worth starting regardless as a backstop.
