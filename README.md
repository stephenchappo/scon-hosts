# scon-hosts

Host config for Anjie, Trillian and Deepthought in one repo (round 4 decision: the `*-home` repos and `anjie-bin` merge into one hosts repo). Built at greenfield build step 3 on 2026-10-27.

| Folder | Copied from | Commit |
|---|---|---|
| `hosts/trillian/` | `trillian-home` | a2a3d40 |
| `hosts/deepthought/` | `deepthought-home` | c0c0139 |
| `hosts/anjie/` | `anjie-home` | 2ecf726 |
| `hosts/anjie/bin-anjie/` | `anjie-bin` | cc56545 |

## How this copy was made

- **Files only, no history.** The old repos keep their history and stay live until cutover (round 11, D1: nothing in the old setup changes before the step 18 week ends). Machines don't deploy from this repo yet.
- **Skills left out.** Each `.claude/skills/` folder was skipped. Skills move to the system repo (`scon-system`, `.claude/skills/`) at step 7, and Restricted skills go to the Restricted repo.
- **Secrets.** Scanned before the first commit: no secret values found. `hosts/deepthought/host-config/secrets-inventory.md` lists names only. Values live in Bitwarden Secrets Manager from step 5.

## Next

Step 4 adds compose files and units as code, the Claude Code version pin timer, and removes dead MCP entries and duplicate hooks from the copies here first, then on the machines at cutover.
