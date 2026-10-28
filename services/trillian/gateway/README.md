# scon-gateway (Trillian)

The gateway container for greenfield build step 6. **Staged, not deployed.** What it enforces and the tables it reads are documented in `scon-system/gateway/README.md`.

| File | What it is |
|---|---|
| `app/gateway.py` | The service (FastAPI): chat routes, tool endpoints, health (no admin endpoint; policy loads at start) |
| `app/policy.py` | Loads and checks the tables; `python3 -m app.policy DIR` checks a candidate |
| `app/serve.py` | Runs the machine (8640) and cloud (8641) listeners on loopback in one process |
| `tests/` | 72 tests, no network (every upstream is mocked) |
| `compose.yaml`, `Dockerfile` | Host network with loopback-only listeners, read-only, all capabilities dropped, runs as the deploying user |
| `gen_override.py` | Writes `compose.override.yaml` naming each token verifier and tool credential (names only) |
| `deploy.sh` | Check, preflight, switch from a per-commit worktree, health, roll back on any failure. Refuses to start until `~/.config/scon-gateway/LIVE` exists |
| `health.sh` | autodeploy-style health check |

## Test

```bash
SYSTEM=~/work/scon-system
cd ~/work/scon-hosts/services/trillian/gateway
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest==9.2.0
GATEWAY_TABLES=$SYSTEM/gateway .venv/bin/python -m pytest -q tests
```

Or in the container: `./deploy.sh --check` (tests origin/main of scon-system; starts nothing).

## Going live (not before the D9 review and Scon's card)

1. Secrets Manager project `gateway` holds `OPENROUTER_API` and one `GW_TOKEN_SHA256_<ID>` per token (step 5).
2. The Restricted repo exists on Trillian, so the full-text log has a home (`GATEWAY_RESTRICTED_LOG_DIR`, step 8).
3. `mkdir -p ~/.config/scon-gateway && touch ~/.config/scon-gateway/LIVE`, then `./deploy.sh`.
4. The ingress in `scon-system/gateway/INGRESS.md`: `tailscale serve` to 8640, `cloudflared` to 8641, and `GW_CF_TEAM_DOMAIN` and `GW_CF_AUD` set.
5. Add the gateway to `homelab-services/services.yaml` (port 8640) and to autodeploy.
