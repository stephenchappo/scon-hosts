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
import asyncio, copy, datetime, fcntl, hashlib, hmac, json, math, os, pathlib, re, uuid

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
MAX_BODY_BYTES = 512 * 1024  # with max_output_tokens, bounds what one call can cost
MAX_UPSTREAM = 16            # hosted and tool calls in flight at once
# Billing outcome when a provider answers with an error and no cost: these are refused before
# any generation, so the reservation is released. Everything else (403/451 declines, 5xx, a
# timeout or a broken read) may have been billed, so the reservation stays as the estimate.
UNBILLED_STATUS = {400, 401, 402, 404, 413, 422, 429}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


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
    return pol.path_pattern_ok(path) and "*" not in path


CONTROL_HEADERS = ("authorization", "x-tier", "x-source", "x-source-path", "x-run-id", "x-run-estimate-usd",
                   "cf-access-jwt-assertion")


def duplicated_control_header(request):
    return any(len(request.headers.getlist(h)) > 1 for h in CONTROL_HEADERS)


def count_of(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10 ** 9 else None


def sanitize(v, secrets):
    """Redact credentials from decoded JSON values, so escaped forms (a\\/b, \\u0061) can't slip past."""
    if isinstance(v, str):
        for x in secrets:
            v = v.replace(x, "[redacted]")
        return v
    if isinstance(v, list):
        return [sanitize(x, secrets) for x in v]
    if isinstance(v, dict):
        return {sanitize(k, secrets): sanitize(x, secrets) for k, x in v.items()}
    return v


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
        self.corrupt = False
        if not self.path.exists():
            return
        settled = {}
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                k = e.get("kind")
            except (ValueError, AttributeError):
                self.corrupt = True  # a smaller total than the truth is never acceptable: stop
                continue
            if k == "reserve":
                self.open[e["rid"]] = (e["ts"][:7], e["token"], e["run"], e["amount"])
            elif k == "call" and e.get("rid"):
                settled[e["rid"]] = e
            elif k == "alert" and e.get("month") == self.month:
                self.alerted.add(e["percent"])
            elif k == "tool-attempt" and e.get("ts", "")[:10] == now().date().isoformat():
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
        if self.ledger.corrupt:
            self.accounting_ok = False
        self.lock_file = None
        try:  # one gateway process per ledger: the asyncio lock is only good inside one process
            self.lock_file = open(str(self.shared_log) + ".lock", "w")
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.accounting_ok = False
        self.upstream = asyncio.Semaphore(MAX_UPSTREAM)
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
            pol.save_lkg(self.config_dir, self.state_dir, p.digest)
        except OSError as e:
            self.policy, self.degraded, self.load_error = p, True, [f"could not save last-known-good: {e}"]
            return True, p.digest
        self.policy, self.degraded, self.load_error = p, False, None
        return True, p.digest

    def load_canaries(self):
        """The registry must parse and every planted entry must be a sha256; otherwise it is empty
        and hosted and tool calls fail closed."""
        extra = [h for h in self.env.get("GW_CANARY_SHA256", "").split(",") if h]
        f = pathlib.Path(self.env.get("GW_CANARIES_FILE", "/system/benchmark/canaries.json"))
        try:
            reg = json.loads(f.read_text())
            hashes = [v["marker_sha256"] for v in reg.values() if v.get("planted") or v.get("marker_sha256")]
        except (OSError, ValueError, AttributeError, TypeError, KeyError):
            return set()
        hashes += extra
        if not hashes or not all(isinstance(h, str) and HEX64.match(h) for h in hashes):
            return set()
        return set(hashes)

    # --- listeners and auth ---------------------------------------------------
    def on_cloud(self, request):
        server = request.scope.get("server") or ("", 0)
        return server[1] == self.cloud_port

    def verify_access(self, assertion, team, aud):
        import jwt
        if self.jwk_client is None:
            self.jwk_client = jwt.PyJWKClient(f"https://{team}/cdn-cgi/access/certs", cache_keys=True,
                                              lifespan=3600, timeout=5)
        key = self.jwk_client.get_signing_key_from_jwt(assertion).key
        return jwt.decode(assertion, key, algorithms=["RS256"], audience=aud, issuer=f"https://{team}")

    async def access_ok(self, request, b):
        """Cloud listener: a valid Cloudflare Access JWT for this token's own service token.
        Key fetches run off the event loop with a timeout, so they can't stall the other listener."""
        team, aud = self.env.get("GW_CF_TEAM_DOMAIN"), self.env.get("GW_CF_AUD")
        assertion = request.headers.get("cf-access-jwt-assertion")
        if not (team and aud and assertion):
            return False
        try:
            claims = await asyncio.wait_for(asyncio.to_thread(self.verify_access, assertion, team, aud), 6)
        except Exception:
            return False
        want = b.get("access_client_id")
        return bool(want) and claims.get("common_name") == want

    async def binding(self, request):
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
        if cloud and not await self.access_ok(request, b):
            return None, "unknown token"
        return b, None

    # --- logging --------------------------------------------------------------
    def write(self, path, entry, private=False):
        """Append one line and sync it. private: the Restricted log, 0700 folder and 0600 file."""
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o777)
        if private:
            os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600 if private else 0o644)
        if private:
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a") as f:
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
                return None, (402, f"${limit} without a card is used for today; a bigger run needs Scon's card"
                              if not approved else f"this run has used its ${limit} budget")
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
                    self.write(self.restricted_log, {**entry, **full}, private=True)
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
        """(ledger key, run name, log tag). A run Scon approved for this token has its own budget;
        everything else the token does in a day shares one unapproved allowance, so new run ids
        never buy a fresh $5."""
        run = request.headers.get("x-run-id")
        if run is not None and not RUN_ID.match(run):
            return None
        approved = self.policy.runs.get(run) if run else None
        if approved and approved["token"] == b["id"]:
            key = run_key(b["id"], run)
        else:
            key = run_key(b["id"], "unapproved-" + now().date().isoformat())
        return key, run, run_key(b["id"], run or "-")

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
            # Only this process changes model, and only to the route's next entry.
            out["provider"] = {"allow_fallbacks": False}
            if route.get("zdr"):
                out["provider"].update(zdr=True, data_collection="deny")
        try:
            async with self.upstream:
                r = await self.client.post(url, json=out, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            return None, ("never sent", f"upstream unreachable: {type(e).__name__}")
        except httpx.HTTPError as e:
            return None, ("maybe billed", f"upstream failed mid-call: {type(e).__name__}")
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
        try:
            if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
                return deny(413, "request too large")
        except ValueError:
            return deny(400, "bad content-length")
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
                             "canaries": len(gw.canaries), "month_usd": round(gw.ledger.total, 4),
                             "release": gw.env.get("GW_RELEASE")},
                            status_code=200 if ok else 503)

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        b, why = await gw.binding(request)
        if not b:
            return deny(401, why)
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return deny(413, "request too large")
        try:
            body = json.loads(raw)
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
                "project": b["project"], "route": rid, "tier": tier, "run": run[2]}
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
        returns = {*route["models"], *route.get("returns", [])}

        tried = []
        for model in route["models"]:
            rsv, refusal = await gw.admit(b, run, reserve)
            if refusal:
                await gw.note({**base, "kind": "refusal", "status": "refused-budget"})
                return deny(*refusal, tried=tried) if tried else deny(*refusal)
            r, err = await gw.call_model(route, model, body)
            entry = {**base, "model": model, "fallbacks": len(tried), "title": title,
                     "badge": "restricted" if tier in pol.RESTRICTED else None}
            if err:
                billed = err[0] == "maybe billed" and not local
                await gw.settle(rsv, {**entry, "status": "unreachable", "cost_usd": 0.0,
                                      "cost_kind": "estimated" if billed else ("flat" if local else "none")})
                tried.append({"model": model, "result": err[1]})
                if billed:
                    break  # it may have run: don't pay for a second model on a guess
                continue
            data = parse(r)
            cost = 0.0 if local else cost_of((data or {}).get("usage"))
            u = (data or {}).get("usage") if isinstance((data or {}).get("usage"), dict) else {}
            entry.update(tokens_in=count_of(u.get("prompt_tokens")), tokens_out=count_of(u.get("completion_tokens")),
                         cost_usd=cost if cost is not None else 0.0,
                         cost_kind="flat" if local else ("exact" if cost is not None else "estimated"))
            if r.status_code != 200 and cost is None and r.status_code in UNBILLED_STATUS:
                entry.update(cost_usd=0.0, cost_kind="none")
            if declined(r, data):
                await gw.settle(rsv, {**entry, "status": "declined"})
                tried.append({"model": model, "result": "declined"})
                continue
            if r.status_code != 200 or data is None:
                await gw.settle(rsv, {**entry, "status": f"http {r.status_code}"})
                tried.append({"model": model, "result": f"http {r.status_code}"})
                if r.status_code in RETRY_STATUS and entry["cost_kind"] == "none":
                    continue
                break
            if not local and data.get("model") not in returns:
                # Answered by a model the route doesn't name: pay for it, don't serve it, stop.
                await gw.settle(rsv, {**entry, "status": "model-mismatch"})
                await gw.ntfy("Gateway: a provider answered as a model the route doesn't name; call refused", high=True)
                return deny(502, "the provider answered as a model this route doesn't name")
            full = {"messages": body.get("messages"), "completion": data.get("choices")} if tier in pol.RESTRICTED else None
            await gw.settle(rsv, {**entry, "status": "ok"}, full)
            if entry["cost_kind"] == "estimated":
                await gw.ntfy("Gateway: a provider sent no cost; the reservation was charged", high=True)
            return JSONResponse(data)
        await gw.note({**base, "kind": "refusal", "status": "failed", "tried": tried})
        return deny(502, "every model on the route declined or failed", tried=tried)

    @app.post("/v1/tools/{account}/{verb}")
    async def tool(account: str, verb: str, request: Request):
        b, why = await gw.binding(request)
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
        # The content's tier must be one the token may send, never Tier-1, and no higher than the account's.
        if why or tier == "tier1" or tier not in b["tiers"] or acct_tier not in b["tiers"] \
                or pol.rank(tier) > pol.rank(acct_tier):
            return deny(403, "tier not allowed for this tool")
        try:
            req = await request.json()
        except ValueError:
            return deny(400, "body must be JSON")
        if not isinstance(req, dict):
            return deny(400, "body must be an object")
        if not gw.canaries:
            return deny(503, "canary registry missing; failing closed")
        if gw.canary_hit(request, req):
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
        async with gw.ledger.lock:  # counted durably before the call, so a restart can't forget it
            gw.ledger.roll()
            if not gw.accounting_ok:
                return deny(503, "log not writable; tool calls stopped")
            if gw.ledger.tools.get(b["id"], 0) >= limit:
                return deny(429, "this token's tool calls for today are used")
            try:
                gw.write_shared({"kind": "tool-attempt", "ts": now().isoformat(), "token": b["id"]})
            except AccountingError:
                return deny(503, "log not writable; tool calls stopped")
            gw.ledger.tools[b["id"]] = gw.ledger.tools.get(b["id"], 0) + 1
        header = a["auth"]["format"].replace("{secret}", secret)
        base = {"kind": "tool", "ts": now().isoformat(), "token": b["id"], "environment": b["environment"],
                "project": b["project"], "account": account, "verb": verb,
                "path": None if acct_tier != "open" else path,
                "badge": "restricted" if acct_tier != "open" else None}
        url = httpx.URL(spec["base"].rstrip("/") + path)
        if url.raw_path.decode().split("?")[0] != (httpx.URL(spec["base"]).raw_path.decode().rstrip("/") + path):
            return deny(403, "path not allowed for this tool")  # httpx would send a different path than the one checked
        try:
            async with gw.upstream:
                r = await gw.client.request(spec["method"], url,
                                        headers={a["auth"]["header"]: header},
                                        params=query, json=payload)
        except httpx.HTTPError as e:
            await gw.note({**base, "status": f"unreachable {type(e).__name__}"})
            return deny(502, f"{account} unreachable")
        await gw.note({**base, "status": r.status_code})
        secrets = sorted({header, secret}, key=len, reverse=True)
        try:
            return JSONResponse({"status": r.status_code, "json": sanitize(r.json(), secrets)})
        except ValueError:
            return JSONResponse({"status": r.status_code, "text": sanitize(r.text, secrets)})

    return app
