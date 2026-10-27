# blank-slate

An isolated Claude Code container. Launch with `~/bin/blank`.

**Source of truth: `~/system/blank-slate/` in the HOME repo** — the launcher,
`settings.json`, this README, `install.sh` and `uninstall.sh`. Installed as
copies, matching `~/system/power-profile-auto/`. After editing anything there,
re-run `bash ~/system/blank-slate/install.sh`.

Layout:

    /srv/blank-slate/
      config/      CLAUDE_CONFIG_DIR — transcripts, credentials. Nothing else.
      workspace/   the session's cwd; the only place its file tools can touch
      settings.json  deny rules, passed via --settings
      README.md    this file

Why /srv and not $HOME: CLAUDE.md discovery walks up from cwd to /, so anything
under /home/scon inherits ~/CLAUDE.md and ~/.claude/CLAUDE.md. /srv has no
CLAUDE.md ancestor, is not a git repo, and is not synced anywhere.

Verified 2026-09-17:
  - reading /home/scon/CLAUDE.md from inside the container is denied
  - transcripts land in config/projects/-srv-blank-slate-workspace only;
    nothing is written under ~/.claude
  - container .claude.json has no mcpServers and no enabled plugins

Not isolated from: the Anthropic account. Sessions still run through the API
under the same login (config/.credentials.json is a copy of the host token).
For isolation from that too, use a local model on Deepthought.
