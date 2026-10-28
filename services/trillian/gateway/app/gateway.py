"""The Trillian gateway (greenfield target design 2.7; round 11 D3, D7, D8; D9 review fixes).

The only process that holds provider keys and tool credentials. Deny by default:
a call is served only when its token, listener, route, tier, budget and (for tools)
the approved-models list all say yes. Anything it can't decide fails closed.

Two listeners share one app (app/serve.py):
  machine port (8640)  loopback, and the tailnet through `tailscale serve`
  cloud port (8641)    reached only through the Cloudflare tunnel; every request needs a
                       valid Cloudflare Access JWT as well as a cloud-ingress gateway token

Endpoints
  POST /v1/chat/completions      OpenAI-shaped; "model" must be "route:<id>"
  POST /v1/tools/{account}/{verb} {"path": "/...", "query": {}, "json": {}}
  GET  /healthz                  full detail on the machine port, ok/not ok on the cloud port
There is no admin endpoint: `tailscale serve` makes tailnet callers look like loopback, so
a policy change takes effect by restarting the container (deploy.sh), never over HTTP.

Request headers the caller may set
  X-Tier          open | restricted-teaching | restricted-explicit | tier1
  X-Source-Path   file the content came from; Tier-1 paths force tier1
  X-Source        content source; Google connector output and unknown sources are Tier-1 (D4)
  X-Run-Id        [a-z0-9._-]{1,48}; calls without one join the token's run for the day
  X-Run-Estimate-USD   for the $5 run gate
  X-Title         short title for the cost log, Open tier only
"""
import asyncio, copy, datetime, hashlib, hmac, json, math, os, pathlib, re, uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import policy as pol

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CANARY = re.compile(r"CANARY-[A-Z]{2}-\d{6,}")
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
DECLINE_STATUS = {403, 451}
RETRY_STATUS = {429, 500, 502, 503, 504}
# The only request fields passed upstream. Anything else (models, route, provider, plugins,
# transforms, user, ...) could widen the route or send the prompt somewhere else: refused.
BODY_KEYS = {"model", "messages", "temperature", "top_p", "top_k", "max_tokens", "stop", "seed",
             "response_format", "tools", "tool_choice", "frequency_penalty", "presence_penalty",
             "repetition_penalty", "reasoning", "stream"}
MIN_TOKEN_SECRET = 43  # secrets.token_urlsafe(32)
DEFAULT_TOOL_CALLS = 100


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def deny(status, why, **extra):
    return JSONResponse({"error": {"code": status, "message": why, **extra}}, status_code=status)


def run_key(token_id, run):
    return hashlib.sha256(f"{token_id}:{run}".encode()).hexdigest()[:16]


def path_ok(path, pattern):
    """A '*' matches one path segment only, so /playlists/* never reaches /playlists/x/tracks."""
    rx = "".join("[^/?#]+" if c == "*" else re.escape(c) for c in pattern)
    return re.fullmatch(rx, path) is not None


def clean_path(path):
    """Literal paths only: no escapes, traversal, separators in disguise or control characters."""
    return (isinstance(path, str) and path.startswith("/") and ".." not in path and "//" not in path
            and not re.search(r"[%;\\?#\s\x00-\x1f\x7f]", path))


CONTROL_HEADERS = ("authorization", "x-tier", "x-source", "x-source-path", "x-run-id", "x-run-estimate-usd",
                   "cf-access-jwt-assertion")


def duplicated_control_header(request):
    return any(len(request.headers.getlist(h)) > 1 for h in CONTROL_HEADERS)


def cost_of(usage):
    c = (usage or {}).get("cost")
    if isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) and c >= 0:
        return float(c)
    return None


class AccountingError(Exception):
    pass


class Ledger:
    """Durable spend. A hosted call writes a reserve line before it is sent and a settle line
    after; a reserve with no settle (a crash, a lost response) stays charged. Month totals cover
    the overall cap and each token's budget; run totals are lifetime, so a month boundary or a
    restart never refreshes a run's allowance."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.lock = asyncio.Lock()
        self.month = now().strftime("%Y-%m")
        self.total, self.by_token, self.runs, self.tools, self.alerted = 0.0, {}, {}, {}, set()
        self.open = {}  # reserve id -> (month, token, run, amount)
        self._tool_day = now().date()
        if not self.path.exists():
            return
        settled = {}
        for line in self.path.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            k = e.get("kind")
            if k == "reserve":
                self.open[e["rid"]] = (e["ts"][:7], e["token"], e["run"], e["amount"])
            elif k == "call" and e.get("rid"):
                settled[e["rid"]] = e
            elif k == "alert" and e.get("month") == self.month:
                self.alerted.add(e["percent"])
            elif k == "tool" and e.get("ts", "")[:10] == now().date().isoformat():
                self.tools[e["token"]] = self.tools.get(e["token"], 0) + 1
        for rid, (month, token, run, amount) in list(self.open.items()):
            s = settled.get(rid)
            cost = amount if s is None or s.get("cost_kind") == "estimated" else (s.get("cost_usd") or 0.0)
            self._add(month, token, run, cost)
            if s is not None:
                del self.open[rid]

    def _add(self, month, token, run, cost):
        if month == self.month:
            self.total += cost
            self.by_token[token] = self.by_token.get(token, 0.0) + cost
        self.runs[run] = self.runs.get(run, 0.0) + cost

    def roll(self):
        m = now().strftime("%Y-%m")
        if m != self.month:
            # Open reservations stay charged to the month they were made in, as on a rebuild.
            self.month, self.total, self.by_token, self.alerted = m, 0.0, {}, set()
        if self._tool_day != now().date():
            self.tools, self._tool_day = {}, now().date()


class Gateway:
    def __init__(self, config_dir, state_dir, env=None, transport=None):
        self.config_dir, self.state_dir = pathlib.Path(config_dir), pathlib.Path(state_dir)
        self.env = os.environ if env is None else env
        self.client = httpx.AsyncClient(transport=transport, timeout=120)
        self.policy, self.degraded, self.load_error = None, False, None
        self.accounting_ok, self.jwk_client = True, None
        self.cloud_port = int(self.env.get("GW_CLOUD_PORT", "8641"))
        self.reload()
        logs = self.policy.limits["logs"] if self.policy else {"shared": str(self.state_dir / "calls.jsonl")}
        self.shared_log = pathlib.Path(self.env.get("GW_SHARED_LOG", logs["shared"]))
        self.restricted_log = pathlib.Path(self.env.get("GW_RESTRICTED_LOG", logs.get("restricted", "")))
        try:
            self.shared_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.shared_log, "a"):
                pass
        except OSError:
            self.accounting_ok = False
        self.ledger = Ledger(self.shared_log)
        self.canaries = self.load_canaries()

    # --- policy ---------------------------------------------------------------
    def reload(self):
        try:
            p = pol.load(self.config_dir)
        except pol.PolicyError as e:
            self.load_error = e.problems
            if self.policy is None and (self.state_dir / "lkg").exists():
                try:
                    self.policy, self.degraded = pol.load(self.state_dir / "lkg"), True
                except pol.PolicyError:
                    self.policy = None
            return False, e.problems
        try:
            pol.save_lkg(self.config_dir, self.state_dir)
        except OSError as e:
            self.policy, self.degraded, self.load_error = p, True, [f"could not save last-known-good: {e}"]
            return True, p.digest
        self.policy, self.degraded, self.load_error = p, False, None
        return True, p.digest

    def load_canaries(self):
        hashes = {h for h in self.env.get("GW_CANARY_SHA256", "").split(",") if h}
        f = pathlib.Path(self.env.get("GW_CANARIES_FILE", "/system/benchmark/canaries.json"))
        try:
            hashes |= {v["marker_sha256"] for v in json.loads(f.read_text()).values() if v.get("marker_sha256")}
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        return hashes

    # --- listeners and auth ---------------------------------------------------
    def on_cloud(self, request):
        server = request.scope.get("server") or ("", 0)
        return server[1] == self.cloud_port

    def access_ok(self, request, b):
        """Cloud listener: a valid Cloudflare Access JWT, for this token's service token if it names one."""
        team, aud = self.env.get("GW_CF_TEAM_DOMAIN"), self.env.get("GW_CF_AUD")
        assertion = request.headers.get("cf-access-jwt-assertion")
        if not (team and aud and assertion):
            return False
        try:
            import jwt
            if self.jwk_client is None:
                self.jwk_client = jwt.PyJWKClient(f"https://{team}/cdn-cgi/access/certs", cache_keys=True)
            key = self.jwk_client.get_signing_key_from_jwt(assertion).key
            claims = jwt.decode(assertion, key, algorithms=["RS256"], audience=aud, issuer=f"https://{team}")
        except Exception:
            return False
        want = b.get("access_client_id")
        return not want or claims.get("common_name") == want

    def binding(self, request):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer gw."):
            return None, "missing or malformed gateway token"
        token = auth[len("Bearer "):]
        parts = token.split(".")
        if len(parts) != 3 or len(parts[2]) < MIN_TOKEN_SECRET:
            return None, "unknown token"
        b = self.policy.tokens.get(parts[1])
        want = self.env.get("GW_TOKEN_SHA256_" + parts[1].upper().replace("-", "_"), "")
        got = hashlib.sha256(token.encode()).hexdigest()
        if not b or not want or not hmac.compare_digest(want, got):
            return None, "unknown token"
        if pol._date(b["expires"]) < now().date():
            return None, "token expired"
        cloud = self.on_cloud(request)
        if cloud != (b["ingress"] == "cloud"):
            return None, "unknown token"
        if cloud and not self.access_ok(request, b):
            return None, "unknown token"
        return b, None

    # --- logging --------------------------------------------------------------
    def write(self, path, entry):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def write_shared(self, entry):
        try:
            self.write(self.shared_log, entry)
        except OSError as e:
            self.accounting_ok = False
            raise AccountingError(str(e))

    async def note(self, entry):
        """A refusal or tool line: no cost. Never carries caller text beyond validated fields."""
        async with self.ledger.lock:
            try:
                self.write_shared({**entry, "cost_usd": 0.0, "cost_kind": "none"})
            except AccountingError:
                pass

    async def admit(self, b, run, amount):
        """Check every limit with this call's reservation included, then write the reserve line."""
        lim = self.policy.limits
        async with self.ledger.lock:
            self.ledger.roll()
            if not self.accounting_ok:
                return None, (503, "cost log not writable; hosted calls stopped")
            if self.ledger.total + amount > lim["monthly_cap_usd"]:
                return None, (402, "monthly cap reached")
            if self.ledger.by_token.get(b["id"], 0.0) + amount > b["monthly_usd"]:
                return None, (402, "this token's monthly budget is used")
            approved = self.policy.runs.get(run[1])
            approved = approved if approved and approved["token"] == b["id"] else None
            limit = approved["budget_usd"] if approved else lim["unapproved_run_spend_usd"]
            if self.ledger.runs.get(run[0], 0.0) + amount > limit:
                return None, (402, f"this run has used its ${limit} budget")
            rid = uuid.uuid4().hex
            entry = {"kind": "reserve", "rid": rid, "ts": now().isoformat(), "token": b["id"], "run": run[0],
                     "amount": amount}
            try:
                self.write_shared(entry)
            except AccountingError:
                return None, (503, "cost log not writable; hosted calls stopped")
            self.ledger.open[rid] = (self.ledger.month, b["id"], run[0], amount)
            self.ledger._add(self.ledger.month, b["id"], run[0], amount)
            return rid, None

    async def settle(self, rid, entry, full=None):
        """Replace the reservation with the exact cost; a missing cost keeps the reservation."""
        async with self.ledger.lock:
            month, token, run, amount = self.ledger.open.pop(rid)
            if entry["cost_kind"] == "estimated":
                entry["cost_usd"] = amount
            else:
                self.ledger._add(month, token, run, entry["cost_usd"] - amount)
            entry = {**entry, "rid": rid}
            try:
                self.write_shared(entry)
            except AccountingError:
                pass  # the reserve line stays charged on restart; new hosted calls are refused
            if full is not None and self.restricted_log.name:
                try:
                    self.write(self.restricted_log, {**entry, **full})
                except OSError:
                    pass
            await self.check_alerts()

    async def check_alerts(self):
        cap = self.policy.limits["monthly_cap_usd"]
        for pct in sorted(self.policy.limits["alerts_percent"]):
            if self.ledger.total >= cap * pct / 100 and pct not in self.ledger.alerted:
                self.ledger.alerted.add(pct)
                try:
                    self.write_shared({"kind": "alert", "month": self.ledger.month, "percent": pct,
                                       "total_usd": round(self.ledger.total, 4), "cap_usd": cap,
                                       "ts": now().isoformat()})
                except AccountingError:
                    pass
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

    # --- tiers, runs, canaries ------------------------------------------------
    def tier_of(self, request, b):
        tier = (request.headers.get("x-tier") or b["default_tier"]).strip().lower()
        if tier not in pol.TIERS:
            return None, "unknown tier"
        if self.policy.is_tier1_source(request.headers.get("x-source-path"), request.headers.get("x-source")):
            tier = "tier1"
        if pol.rank(tier) < pol.rank(b["default_tier"]):
            tier = b["default_tier"]
        return tier, None

    def run_of(self, request, b):
        """(ledger key, run name). No X-Run-Id: the token's own run for the day."""
        run = request.headers.get("x-run-id")
        if run is None:
            run = "auto-" + now().date().isoformat()
        elif not RUN_ID.match(run):
            return None
        return run_key(b["id"], run), run

    def canary_hit(self, request, body):
        text = json.dumps(body) + "\n" + "\n".join(request.headers.values())
        return any(hashlib.sha256(m.encode()).hexdigest() in self.canaries for m in CANARY.findall(text))

    # --- upstream -------------------------------------------------------------
    async def call_model(self, route, model, body):
        out = copy.deepcopy(body)
        out["model"] = model
        if self.policy.provider(route) == "ollama":
            url = self.env.get("GW_OLLAMA_URL", "http://100.78.161.123:11434") + "/v1/chat/completions"
            headers = {}
        else:
            key = self.env.get("OPENROUTER_API")
            if not key:
                return None, "no provider key"
            url, headers = OPENROUTER_URL, {"Authorization": f"Bearer {key}", "X-Title": "scon-gateway"}
            out["usage"] = {"include": True}
            if route.get("zdr"):
                out["provider"] = {"zdr": True, "data_collection": "deny", "allow_fallbacks": False}
        try:
            r = await self.client.post(url, json=out, headers=headers)
        except httpx.HTTPError as e:
            return None, f"upstream unreachable: {type(e).__name__}"
        return r, None


def parse(r):
    try:
        data = r.json()
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def declined(r, data):
    if r.status_code in DECLINE_STATUS:
        return True
    if r.status_code == 200 and data is not None:
        ch = data.get("choices") or [{}]
        return isinstance(ch, list) and isinstance(ch[0], dict) and ch[0].get("finish_reason") == "content_filter"
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
        if duplicated_control_header(request):
            return deny(400, "a control header was sent more than once")
        return await call_next(request)

    @app.get("/healthz")
    async def healthz(request: Request):
        ok = gw.policy is not None and gw.accounting_ok and bool(gw.canaries)
        if gw.on_cloud(request):
            return JSONResponse({"ok": ok}, status_code=200 if ok else 503)
        return JSONResponse({"ok": ok, "degraded": gw.degraded, "digest": gw.policy.digest if gw.policy else None,
                             "load_error": gw.load_error, "accounting_ok": gw.accounting_ok,
                             "canaries": len(gw.canaries), "month_usd": round(gw.ledger.total, 4)},
                            status_code=200 if ok else 503)

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        b, why = gw.binding(request)
        if not b:
            return deny(401, why)
        try:
            body = await request.json()
        except ValueError:
            return deny(400, "body must be JSON")
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return deny(400, "body must be an object with a messages list")
        extra = sorted(set(body) - BODY_KEYS)
        if extra:
            return deny(400, f"fields not accepted: {extra}")
        if body.get("stream"):
            return deny(400, "streaming is not supported yet; cost must be read from the full response")
        name = str(body.get("model", ""))
        if not name.startswith("route:"):
            return deny(400, 'model must be "route:<id>"; raw model names are not accepted')
        rid = name[len("route:"):]
        route = gw.policy.routes.get(rid)
        if not route or rid not in b["routes"]:
            return deny(403, "route not allowed for this token")
        tier, why = gw.tier_of(request, b)
        if why:
            return deny(400, why)
        run = gw.run_of(request, b)
        if run is None:
            return deny(400, "X-Run-Id must be 1-48 of a-z 0-9 . _ -")
        base = {"kind": "call", "ts": now().isoformat(), "token": b["id"], "environment": b["environment"],
                "project": b["project"], "route": rid, "tier": tier, "run": run[0]}
        if not gw.canaries:
            return deny(503, "canary registry missing; failing closed")
        if gw.canary_hit(request, body):
            await gw.note({**base, "kind": "refusal", "status": "refused-canary"})
            return deny(451, "planted canary in the request; refused before any call")
        if tier not in b["tiers"]:
            await gw.note({**base, "kind": "refusal", "status": "refused-tier"})
            return deny(403, f"this token may not send {tier} content")
        if tier == "tier1" and gw.policy.provider(route) != "ollama":
            await gw.note({**base, "kind": "refusal", "status": "refused-tier1"})
            return deny(403, "Tier-1 content is never sent to a hosted route; use route:local or Claude directly")
        if tier not in route["tiers"]:
            return deny(403, f"route {rid} does not carry {tier}")
        try:
            est = float(request.headers.get("x-run-estimate-usd", "0") or 0)
        except ValueError:
            return deny(400, "bad X-Run-Estimate-USD")
        lim = gw.policy.limits
        approved = gw.policy.runs.get(run[1])
        if not math.isfinite(est) or (est > lim["run_gate_usd"] and not (approved and approved["token"] == b["id"])):
            await gw.note({**base, "kind": "refusal", "status": "refused-gate"})
            return deny(402, f"a run estimated over ${lim['run_gate_usd']} needs Scon's card first "
                             "(ask on Your Move, then add it to approved-runs.yaml)")
        cap = lim["max_output_tokens"]
        if not isinstance(body.get("max_tokens"), int) or not 0 < body["max_tokens"] <= cap:
            body["max_tokens"] = cap
        title = (request.headers.get("x-title") or "")[:80] if tier == "open" else None
        local = gw.policy.provider(route) == "ollama"
        reserve = 0.0 if local else route.get("reserve_usd", lim["reserve_per_call_usd"])

        tried = []
        for model in route["models"]:
            rsv, refusal = await gw.admit(b, run, reserve)
            if refusal:
                await gw.note({**base, "kind": "refusal", "status": "refused-budget"})
                return deny(*refusal, tried=tried) if tried else deny(*refusal)
            r, err = await gw.call_model(route, model, body)
            data = parse(r) if r is not None else None
            cost = 0.0 if local else cost_of((data or {}).get("usage"))
            entry = {**base, "model": model, "fallbacks": len(tried), "title": title,
                     "badge": "restricted" if tier in pol.RESTRICTED else None,
                     "cost_usd": cost if cost is not None else 0.0,
                     "cost_kind": "flat" if local else ("exact" if cost is not None else "estimated")}
            if err:
                entry.update(status="unreachable", cost_usd=0.0, cost_kind="none" if not local else "flat")
                await gw.settle(rsv, entry)
                tried.append({"model": model, "result": err})
                continue
            u = (data or {}).get("usage") or {}
            entry.update(tokens_in=u.get("prompt_tokens"), tokens_out=u.get("completion_tokens"))
            if r.status_code != 200 and cost is None:
                entry.update(cost_usd=0.0, cost_kind="none")  # an HTTP error before any work is not billed
            if declined(r, data):
                await gw.settle(rsv, {**entry, "status": "declined"})
                tried.append({"model": model, "result": "declined"})
                continue
            if r.status_code != 200 or data is None:
                await gw.settle(rsv, {**entry, "status": f"http {r.status_code}"})
                tried.append({"model": model, "result": f"http {r.status_code}"})
                if r.status_code in RETRY_STATUS:
                    continue
                break
            got = str(data.get("model") or model)
            if not local and got != model and not got.startswith(model):
                entry["model_returned"] = got[:100]
                await gw.ntfy(f"Gateway: asked for {model}, provider answered as {got[:100]}", high=True)
            full = {"messages": body.get("messages"), "completion": data.get("choices")} if tier in pol.RESTRICTED else None
            await gw.settle(rsv, {**entry, "status": "ok"}, full)
            if entry["cost_kind"] == "estimated":
                await gw.ntfy(f"Gateway: no cost in the usage response for {model}; charged the reservation", high=True)
            return JSONResponse(data)
        await gw.note({**base, "kind": "refusal", "status": "failed", "tried": tried})
        return deny(502, "every model on the route declined or failed", tried=tried)

    @app.post("/v1/tools/{account}/{verb}")
    async def tool(account: str, verb: str, request: Request):
        b, why = gw.binding(request)
        if not b:
            return deny(401, why)
        a = gw.policy.accounts.get(account)
        spec = (a or {}).get("verbs", {}).get(verb)
        if not spec:
            return deny(403, "no such tool")
        if verb not in (b.get("accounts") or {}).get(account, []):
            return deny(403, "token not granted this tool")
        if not gw.policy.model_approved(b["model"], account, verb):
            return deny(403, f"{b['model']} is not on the approved-models list for {account}.{verb}")
        tier, why = gw.tier_of(request, b)
        acct_tier = a.get("tier", "open")
        if why or tier == "tier1" or acct_tier not in b["tiers"]:
            return deny(403, "tier not allowed for this tool")
        if acct_tier == "open" and tier in pol.RESTRICTED:
            return deny(403, "restricted content may not be sent to an open account")
        try:
            req = await request.json()
        except ValueError:
            return deny(400, "body must be JSON")
        if not isinstance(req, dict):
            return deny(400, "body must be an object")
        if gw.canaries and gw.canary_hit(request, req):
            return deny(451, "planted canary in the request; refused before any call")
        path = req.get("path")
        if not clean_path(path) or not any(path_ok(path, p) for p in spec["paths"]):
            return deny(403, "path not allowed for this tool")
        query, payload = req.get("query") or None, req.get("json")
        if verb == "read" and payload is not None:
            return deny(400, "a read carries no body")
        if query is not None and (not isinstance(query, dict) or not set(query) <= set(spec.get("query_keys", []))):
            return deny(403, "query keys not allowed for this tool")
        secret = gw.env.get(a["auth"]["secret"])
        if not secret:
            return deny(503, f"credential for {account} not present; failing closed")
        limit = b.get("tool_calls_per_day", DEFAULT_TOOL_CALLS)
        async with gw.ledger.lock:
            gw.ledger.roll()
            if gw.ledger.tools.get(b["id"], 0) >= limit:
                return deny(429, "this token's tool calls for today are used")
            gw.ledger.tools[b["id"]] = gw.ledger.tools.get(b["id"], 0) + 1
        header = a["auth"]["format"].replace("{secret}", secret)
        base = {"kind": "tool", "ts": now().isoformat(), "token": b["id"], "environment": b["environment"],
                "project": b["project"], "account": account, "verb": verb,
                "path": None if acct_tier != "open" else path,
                "badge": "restricted" if acct_tier != "open" else None}
        try:
            r = await gw.client.request(spec["method"], spec["base"].rstrip("/") + path,
                                        headers={a["auth"]["header"]: header},
                                        params=query, json=payload)
        except httpx.HTTPError as e:
            await gw.note({**base, "status": f"unreachable {type(e).__name__}"})
            return deny(502, f"{account} unreachable")
        await gw.note({**base, "status": r.status_code})
        text = r.text.replace(header, "[redacted]").replace(secret, "[redacted]")
        return JSONResponse({"status": r.status_code, "body": text}, status_code=200)

    return app
