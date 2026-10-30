---
kind: service
use_for:
- browser claude can drive
- headless chromium
- playwright mcp
- click through a website
- screenshot a web page
what: Headless Chromium on eddie, driven through the Playwright MCP server, with every site visit going through the scon-fetch proxy
status: built 2026-10-30
---

# Browser on eddie

A headless Chromium that a Claude Code session drives through the Playwright MCP server: open
pages, click, fill in forms, read the page, take screenshots. Scon chose this on 2026-10-30, over a
watchable desktop (eddie would need 8 GB) or a hosted browser service. It adds nothing to eddie's
bill (estimated $0 a month).

## How it fits together

| Container | What it does |
|---|---|
| `browser` | `mcr.microsoft.com/playwright/mcp:v0.0.83`, headless Chromium, `--isolated` (the profile stays in memory: no saved logins, nothing left on disk). It is on the `inside` network, which Docker gives no route out |
| `proxy` | `scon-fetch proxy` (browser mode, `projects/scon-fetch/scon_fetch/proxy.py`). The browser's only way out. It applies the site book to each HTTPS tunnel, logs each one, and relays the MCP port to `127.0.0.1:8931` on eddie |

The proxy refuses plain http, anything but port 443, our own machines (by name and after DNS), stopped
sites, sites this machine is cooling down from, and sites over today's budget. Hosts with no record
pass uncounted and are logged. Log lines go to eddie's journal and the shared
`~/.local/state/scon-fetch/requests.jsonl`, project `browser`.

## Using it

From a Claude Code session on eddie:

```bash
claude mcp add --transport http browser http://127.0.0.1:8931/mcp
```

Rules for the Claude driving it:

- **No logins to Scon's personal accounts, and no Tier-1 or Restricted data.** eddie is a rented
  server. Each session starts with an empty profile; keep it that way.
- **On a CAPTCHA or "verify you are human" page, stop.** Run `~/eddie/vendor/scon-fetch/bin/scon-fetch block URL "why"`
  so the cooldown starts, and tell Scon. Never work around a block.
- A refused page shows a tunnel error; `requests.jsonl` says why (`refused-stopped`,
  `refused-budget`...).

## Checks

`install.sh` checks that the browser can't reach the internet directly and runs `smoke.py`, which opens
https://example.com through the MCP server. Run it again any time:

```bash
python3 ~/eddie/services/browser/smoke.py
```

## Not yet

- **Reachable only on eddie.** The tailnet policy lets home servers reach eddie on 443 and 22 only, so
  Claude on Trillian or Anjie can't use it yet. Opening it means a `tcp:8931` grant and a
  `tailscale serve` line, which is Scon's call.
- **Loki.** Log lines reach Loki once eddie ships its journal (see eddie's README).
