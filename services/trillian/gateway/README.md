# scon-gateway (Trillian)

The gateway container for greenfield build step 6. **Go-live approved 2026-10-28; being switched on 2026-11 (scon-system `gateway/GO-LIVE.md`).** What it enforces and the tables it reads are documented in `scon-system/gateway/README.md`.

| File | What it is |
|---|---|
| `app/gateway.py` | The service (FastAPI): chat routes, tool endpoints, health (no admin endpoint; policy loads at start) |
| `app/policy.py` | Loads and checks the tables; `python3 -m app.policy DIR` checks a candidate |
| `app/serve.py` | Runs the machine (8640) and cloud (8641) listeners on loopback in one process |
| `tests/` | 82 tests, no network (every upstream is mocked) |
| `compose.yaml`, `Dockerfile` | The gateway (host network, loopback-only listeners, read-only, all capabilities dropped, runs as the deploying user) and its own Cloudflare Tunnel connector (host network, so it reaches 127.0.0.1:8641) |
| `gen_override.py` | Writes `compose.override.yaml` naming each token verifier and tool credential (names only) |
| `deploy.sh` | Check, preflight, build an image tagged by the scon-hosts commit, record the release, start it, check health serves its digest, roll back code and tables on any failure. One at a time (flock). Refuses to start until `~/.config/scon-gateway/LIVE` exists |
| `health.sh` | autodeploy-style health check; with arguments, also that the expected policy digest and release are running |

## Test

```bash
SYSTEM=~/work/scon-system
cd ~/work/scon-hosts/services/trillian/gateway
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest==9.2.0
GATEWAY_TABLES=$SYSTEM/gateway .venv/bin/python -m pytest -q tests
```

Deploy logic: `bash ~/work/scon-hosts/tests/test_gateway_deploy.sh` (fake docker and bws, starts nothing; needs the code committed).

Or in the container: `./deploy.sh --check` (tests origin/main of scon-system; starts nothing).

## Going live

The full order, with what Scon does in Bitwarden and Cloudflare, is `scon-system/gateway/GO-LIVE.md`. In short:

1. Secrets Manager project `gateway` holds `OPENROUTER_API`, `GW_TUNNEL_TOKEN`, `GW_CF_TEAM_DOMAIN`, `GW_CF_AUD` and one `GW_TOKEN_SHA256_<ID>` per token. `bin/gw-token new <id>` makes a token and its verifier (run in a terminal, never in a script).
2. The Restricted log folder only has to be writable; no Restricted token is issued until the Restricted repo exists (step 8).
3. `touch ~/.config/scon-gateway/LIVE`, then `./deploy.sh` (the scon-run script does both and logs).
4. `tailscale serve` to 8640 for Deepthought and Anjie, when a machine token is first issued.
5. Calls, refusals and alerts print one summary line each to the container log, so they reach Loki: `{container=~"scon-gateway.*"} |= "scon-gateway "`.

Tests: `bash ~/work/scon-hosts/tests/test_gw_token.sh`.
