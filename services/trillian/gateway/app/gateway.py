"""The Trillian gateway (greenfield target design 2.7; round 11 D3, D7, D8).

The only process that holds provider keys and tool credentials. Deny by default:
a call is served only when its token, route, tier, budget and (for tools) the
approved-models list all say yes. Anything it can't decide fails closed.

Endpoints
  POST /v1/chat/completions      OpenAI-shaped; "model" must be "route:<id>"
  POST /v1/tools/{account}/{verb} {"path": "/...", "query": {}, "json": {}}
  POST /admin/reload             load the candidate policy; keep last-known-good if it fails
  GET  /healthz                  policy digest, degraded flag, month spend

Request headers the caller may set
  X-Tier          open | restricted-teaching | restricted-explicit | tier1
  X-Source-Path   file the content came from; Tier-1 paths force tier1
  X-Source        content source, e.g. gmail (D4: Google connector output is Tier-1)
  X-Run-Id, X-Run-Estimate-USD   for the $5 run gate
  X-Title         short title for the cost log (dropped for tier1)
"""
import asyncio, copy, datetime, hashlib, hmac, json, os, pathlib, re

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import policy as pol

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CANARY = re.compile(r"CANARY-[A-Z]{2}-\d{6,}")
DECLINE_STATUS = {403, 451}
RETRY_STATUS = {429, 500, 502, 503, 504}


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def deny(status, why, **extra):
    return JSONResponse({"error": {"code": status, "message": why, **extra}}, status_code=status)


class Ledger:
    """Month and per-run spend, rebuilt from the shared log at start."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.month, self.total, self.runs, self.alerted = now().strftime("%Y-%m"), 0.0, {}, set()
        self.lock = asyncio.Lock()
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("kind") == "alert" and e.get("month") == self.month:
                    self.alerted.add(e["percent"])
                elif e.get("kind") == "call" and e.get("ts", "").startswith(self.month):
                    self._add(e.get("run"), e.get("cost_usd") or 0.0)

    def _add(self, run, cost):
        self.total += cost
        if run:
            self.runs[run] = self.runs.get(run, 0.0) + cost

    def roll(self):
        m = now().strftime("%Y-%m")
        if m != self.month:
            self.month, self.total, self.runs, self.alerted = m, 0.0, {}, set()


class Gateway:
    def __init__(self, config_dir, state_dir, env=None, transport=None):
        self.config_dir, self.state_dir = pathlib.Path(config_dir), pathlib.Path(state_dir)
        self.env = os.environ if env is None else env
        self.client = httpx.AsyncClient(transport=transport, timeout=120)
        self.policy, self.degraded, self.load_error = None, False, None
        self.reload()
        logs = self.policy.limits["logs"] if self.policy else {"shared": str(self.state_dir / "calls.jsonl")}
        self.shared_log = pathlib.Path(self.env.get("GW_SHARED_LOG", logs["shared"]))
        self.restricted_log = pathlib.Path(self.env.get("GW_RESTRICTED_LOG", logs.get("restricted", "")))
        self.shared_log.parent.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.shared_log)

    # --- policy ---------------------------------------------------------------
    def reload(self):
        try:
            p = pol.load(self.config_dir)
            pol.save_lkg(self.config_dir, self.state_dir)
            self.policy, self.degraded, self.load_error = p, False, None
            return True, p.digest
        except pol.PolicyError as e:
            self.load_error = e.problems
            if self.policy is None and (self.state_dir / "lkg").exists():
                try:
                    self.policy, self.degraded = pol.load(self.state_dir / "lkg"), True
                except pol.PolicyError:
                    self.policy = None
            return False, e.problems

    # --- auth -----------------------------------------------------------------
    def binding(self, request):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer gw."):
            return None, "missing or malformed gateway token"
        token = auth[len("Bearer "):]
        parts = token.split(".")
        if len(parts) != 3 or not parts[2]:
            return None, "malformed gateway token"
        b = self.policy.tokens.get(parts[1])
        if not b:
            return None, "unknown token"
        want = self.env.get("GW_TOKEN_SHA256_" + parts[1].upper().replace("-", "_"), "")
        got = hashlib.sha256(token.encode()).hexdigest()
        if not want or not hmac.compare_digest(want, got):
            return None, "unknown token"
        if str(b["expires"]) < now().date().isoformat():
            return None, "token expired"
        return b, None

    # --- logging --------------------------------------------------------------
    def write(self, path, entry):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

    async def record(self, entry, full=None):
        """Shared log: cost line only. Restricted full text goes to the Restricted log only."""
        async with self.ledger.lock:
            self.ledger.roll()
            self.write(self.shared_log, entry)
            if full is not None and self.restricted_log.name:
                self.write(self.restricted_log, {**entry, **full})
            self.ledger._add(entry.get("run"), entry.get("cost_usd") or 0.0)
            cap = self.policy.limits["monthly_cap_usd"]
            for pct in sorted(self.policy.limits["alerts_percent"]):
                if self.ledger.total >= cap * pct / 100 and pct not in self.ledger.alerted:
                    self.ledger.alerted.add(pct)
                    self.write(self.shared_log, {"kind": "alert", "month": self.ledger.month, "percent": pct,
                                                 "total_usd": round(self.ledger.total, 4), "cap_usd": cap,
                                                 "ts": now().isoformat()})
                    await self.ntfy(f"Gateway spend at {pct}% of the ${cap} monthly cap "
                                    f"(${self.ledger.total:.2f})", high=pct >= 100)

    async def ntfy(self, text, high=False):
        url = self.env.get("GW_NTFY_URL")
        if not url:
            return
        try:
            await self.client.post(url, content=text.encode(), headers={"Priority": "high" if high else "default",
                                                                         "Title": "Gateway"})
        except httpx.HTTPError:
            pass

    # --- budget ---------------------------------------------------------------
    def budget_refusal(self, request):
        lim = self.policy.limits
        self.ledger.roll()
        if self.ledger.total >= lim["monthly_cap_usd"]:
            return "monthly cap reached"
        run = request.headers.get("x-run-id")
        try:
            est = float(request.headers.get("x-run-estimate-usd", "0") or 0)
        except ValueError:
            return "bad X-Run-Estimate-USD"
        approved = self.policy.runs.get(run) if run else None
        if est > lim["run_gate_usd"] and not approved:
            return f"run estimated at ${est:.2f} is over the ${lim['run_gate_usd']} gate; needs a card"
        if run:
            limit = approved["budget_usd"] if approved else lim["unapproved_run_spend_usd"]
            if self.ledger.runs.get(run, 0.0) >= limit:
                return f"run {run} has used its ${limit} budget"
        elif est > lim["run_gate_usd"]:
            return "an estimate over the gate needs an X-Run-Id"
        return None

    # --- tiers ----------------------------------------------------------------
    def tier_of(self, request, b):
        tier = (request.headers.get("x-tier") or b["default_tier"]).strip().lower()
        if tier not in pol.TIERS:
            return None, f"unknown tier {tier}"
        if self.policy.is_tier1_source(request.headers.get("x-source-path"), request.headers.get("x-source")):
            tier = "tier1"
        if pol.rank(tier) < pol.rank(b["default_tier"]):
            tier = b["default_tier"]
        return tier, None

    def canary_hashes(self):
        hashes = {h for h in self.env.get("GW_CANARY_SHA256", "").split(",") if h}
        f = pathlib.Path(self.env.get("GW_CANARIES_FILE", "/system/benchmark/canaries.json"))
        if f.exists():
            hashes |= {v["marker_sha256"] for v in json.loads(f.read_text()).values() if v.get("marker_sha256")}
        return hashes

    def canary_hit(self, body):
        hashes = self.canary_hashes()
        for m in CANARY.findall(json.dumps(body)):
            if hashlib.sha256(m.encode()).hexdigest() in hashes:
                return True
        return False

    # --- upstream -------------------------------------------------------------
    async def call_model(self, route, model, body):
        out = copy.deepcopy(body)
        out["model"] = model
        out.pop("provider", None)
        if self.policy.provider(route) == "ollama":
            url = self.env.get("GW_OLLAMA_URL", "http://deepthought:11434") + "/v1/chat/completions"
            headers = {}
        else:
            key = self.env.get("OPENROUTER_API")
            if not key:
                return None, "no provider key"
            url, headers = OPENROUTER_URL, {"Authorization": f"Bearer {key}", "X-Title": "scon-gateway"}
            out["usage"] = {"include": True}
            if route.get("zdr"):
                out["provider"] = {"zdr": True, "data_collection": "deny", "allow_fallbacks": True}
        try:
            r = await self.client.post(url, json=out, headers=headers)
        except httpx.HTTPError as e:
            return None, f"upstream unreachable: {type(e).__name__}"
        return r, None


def path_ok(path, pattern):
    """A '*' matches one path segment only, so /playlists/* never reaches /playlists/x/tracks."""
    rx = "".join("[^/?#]+" if c == "*" else re.escape(c) for c in pattern)
    return re.fullmatch(rx, path) is not None


def declined(r):
    if r.status_code in DECLINE_STATUS:
        return True
    if r.status_code == 200:
        try:
            ch = r.json().get("choices") or [{}]
        except ValueError:
            return False
        return ch[0].get("finish_reason") == "content_filter"
    return False


def create_app(config_dir=None, state_dir=None, env=None, transport=None):
    gw = Gateway(config_dir or os.environ.get("GATEWAY_CONFIG", "/config"),
                 state_dir or os.environ.get("GATEWAY_STATE", "/data/state"), env=env, transport=transport)
    app = FastAPI(title="scon-gateway", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gw = gw

    @app.middleware("http")
    async def no_policy_no_service(request, call_next):
        if gw.policy is None and request.url.path != "/healthz":
            return deny(503, "no valid policy loaded; failing closed")
        return await call_next(request)

    @app.get("/healthz")
    async def healthz():
        ok = gw.policy is not None
        return JSONResponse({"ok": ok, "degraded": gw.degraded, "digest": gw.policy.digest if ok else None,
                             "load_error": gw.load_error, "month_usd": round(gw.ledger.total, 4)},
                            status_code=200 if ok else 503)

    @app.post("/admin/reload")
    async def reload(request: Request):
        want = gw.env.get("GW_ADMIN_SHA256", "")
        tok = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not want or not hmac.compare_digest(want, hashlib.sha256(tok.encode()).hexdigest()):
            return deny(401, "admin token required")
        ok, info = gw.reload()
        return JSONResponse({"ok": ok, "digest" if ok else "problems": info,
                             "serving": gw.policy.digest if gw.policy else None}, status_code=200 if ok else 422)

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        b, why = gw.binding(request)
        if not b:
            return deny(401, why)
        try:
            body = await request.json()
        except ValueError:
            return deny(400, "body must be JSON")
        if body.get("stream"):
            return deny(400, "streaming is not supported yet; cost must be read from the full response")
        name = str(body.get("model", ""))
        if not name.startswith("route:"):
            return deny(400, 'model must be "route:<id>"; raw model names are not accepted')
        rid = name[len("route:"):]
        route = gw.policy.routes.get(rid)
        if not route or rid not in b["routes"]:
            return deny(403, f"route {rid} not allowed for this token")
        tier, why = gw.tier_of(request, b)
        if why:
            return deny(400, why)
        base = {"kind": "call", "ts": now().isoformat(), "token": b["id"], "environment": b["environment"],
                "project": b["project"], "route": rid, "tier": tier, "run": request.headers.get("x-run-id")}
        title = None if tier == "tier1" else (request.headers.get("x-title") or "")[:120]
        if gw.canary_hit(body):
            await gw.record({**base, "status": "refused-canary", "cost_usd": 0.0, "cost_kind": "none"})
            return deny(451, "planted canary in the request; refused before any call")
        if tier not in b["tiers"]:
            await gw.record({**base, "status": "refused-tier", "cost_usd": 0.0, "cost_kind": "none"})
            return deny(403, f"this token may not send {tier} content")
        if tier == "tier1" and gw.policy.provider(route) != "ollama":
            await gw.record({**base, "status": "refused-tier1", "cost_usd": 0.0, "cost_kind": "none"})
            return deny(403, "Tier-1 content is never sent to a hosted route; use route:local or Claude directly")
        if tier not in route["tiers"]:
            return deny(403, f"route {rid} does not carry {tier}")
        why = gw.budget_refusal(request)
        if why:
            await gw.record({**base, "status": "refused-budget", "cost_usd": 0.0, "cost_kind": "none"})
            return deny(402, why)

        tried = []
        for model in route["models"]:
            r, err = await gw.call_model(route, model, body)
            if err:
                tried.append({"model": model, "result": err})
                continue
            if declined(r):
                tried.append({"model": model, "result": "declined"})
                continue
            if r.status_code in RETRY_STATUS:
                tried.append({"model": model, "result": f"http {r.status_code}"})
                continue
            if r.status_code != 200:
                tried.append({"model": model, "result": f"http {r.status_code}"})
                break
            data = r.json()
            u = data.get("usage") or {}
            local = gw.policy.provider(route) == "ollama"
            cost = 0.0 if local else u.get("cost")
            entry = {**base, "status": "ok", "model": model, "fallbacks": len(tried), "title": title,
                     "badge": "restricted" if tier in pol.RESTRICTED else None,
                     "tokens_in": u.get("prompt_tokens"), "tokens_out": u.get("completion_tokens"),
                     "cost_usd": float(cost) if cost is not None else 0.0,
                     "cost_kind": "flat" if local else ("exact" if cost is not None else "missing")}
            full = None
            if tier in pol.RESTRICTED:
                full = {"messages": body.get("messages"), "completion": data.get("choices")}
            await gw.record(entry, full)
            if entry["cost_kind"] == "missing":
                await gw.ntfy(f"Gateway: no cost in the usage response for {model}", high=True)
            return JSONResponse(data)
        await gw.record({**base, "status": "failed", "tried": tried, "cost_usd": 0.0, "cost_kind": "none"})
        return deny(502, "every model on the route declined or failed", tried=tried)

    @app.post("/v1/tools/{account}/{verb}")
    async def tool(account: str, verb: str, request: Request):
        b, why = gw.binding(request)
        if not b:
            return deny(401, why)
        a = gw.policy.accounts.get(account)
        spec = (a or {}).get("verbs", {}).get(verb)
        if not spec:
            return deny(403, f"no tool {account}.{verb}")
        if verb not in (b.get("accounts") or {}).get(account, []):
            return deny(403, f"token not granted {account}.{verb}")
        if not gw.policy.model_approved(b["model"], account, verb):
            return deny(403, f"{b['model']} is not on the approved-models list for {account}.{verb}")
        try:
            req = await request.json()
        except ValueError:
            return deny(400, "body must be JSON")
        path = str(req.get("path", ""))
        if not path.startswith("/") or ".." in path or "//" in path or not any(
                path_ok(path, p) for p in spec["paths"]):
            return deny(403, f"path not allowed for {account}.{verb}")
        secret = gw.env.get(a["auth"]["secret"])
        if not secret:
            return deny(503, f"credential for {account} not present; failing closed")
        headers = {a["auth"]["header"]: a["auth"]["format"].replace("{secret}", secret)}
        base = {"kind": "tool", "ts": now().isoformat(), "token": b["id"], "environment": b["environment"],
                "project": b["project"], "account": account, "verb": verb, "path": path,
                "badge": "restricted" if a.get("tier", "open") != "open" else None}
        try:
            r = await gw.client.request(spec["method"], spec["base"].rstrip("/") + path, headers=headers,
                                        params=req.get("query") or None, json=req.get("json"))
        except httpx.HTTPError as e:
            await gw.record({**base, "status": f"unreachable {type(e).__name__}", "cost_usd": 0.0, "cost_kind": "none"})
            return deny(502, f"{account} unreachable")
        if base["badge"]:
            base["path"] = None
        await gw.record({**base, "status": r.status_code, "cost_usd": 0.0, "cost_kind": "none"})
        return JSONResponse({"status": r.status_code, "body": r.text}, status_code=200)

    return app
