"""Gateway tests. No network: every upstream is an httpx.MockTransport.

Run: GATEWAY_TABLES=~/work/scon-system/gateway python3 -m pytest -q tests
(the tables default to ../../../../scon-system/gateway next to this repo).

The shipped tables are only checked for validity; everything else runs on fixture tables,
so a candidate with real tokens still passes (deploy.sh runs this suite on every candidate).
"""
import asyncio, datetime, hashlib, json, os, pathlib, shutil

import httpx, jwt, pytest, yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import policy as pol
from app.gateway import clean_path, create_app, path_ok

HERE = pathlib.Path(__file__).resolve().parent
TABLES = pathlib.Path(os.environ.get("GATEWAY_TABLES") or HERE.parents[4] / "scon-system" / "gateway")
TOK = "gw.personal-sonnet." + "s" * 43      # cloud, Open
RTOK = "gw.restricted-writer." + "r" * 43   # cloud, Restricted
MTOK = "gw.trillian-local." + "m" * 43      # machine, Open + Tier-1
CANARY = "CANARY-RS-123456"
TEAM, AUD = "scon.cloudflareaccess.com", "aud-tag"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def access_jwt(cn="svc-personal", aud=AUD, key=KEY):
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode({"aud": aud, "iss": f"https://{TEAM}", "common_name": cn, "iat": now,
                       "exp": now + datetime.timedelta(minutes=5)}, key, algorithm="RS256")


class FakeJWKs:
    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": KEY.public_key()})()


class Upstream:
    """Records calls; answers per model from a script of (status, finish_reason, cost)."""

    def __init__(self):
        self.calls, self.script, self.tool_body = [], {}, '{"items": []}'

    def __call__(self, request):
        body = json.loads(request.content or b"{}")
        self.calls.append((str(request.url), body, dict(request.headers)))
        if "api.spotify.com" in str(request.url) or "api.fetlife.test" in str(request.url):
            return httpx.Response(200, text=self.tool_body)
        status, finish, cost = self.script.get(body.get("model"), (200, "stop", 0.0012))
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        if cost is not None:
            usage["cost"] = cost
        if status != 200:
            return httpx.Response(status, json={"error": {"code": status}})
        return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": {"content": "hi"}}],
                                         "usage": usage, "model": body.get("model")})


def fixture_tables(cfg):
    exp = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    tokens = {"version": 1, "tokens": [
        {"id": "personal-sonnet", "environment": "personal", "ingress": "cloud", "access_client_id": "svc-personal",
         "model": "anthropic/claude-sonnet-5.5", "routes": ["general-writing", "code", "local"], "tiers": ["open"],
         "default_tier": "open", "accounts": {"spotify": ["read"]}, "project": "personal", "expires": exp,
         "monthly_usd": 30, "tool_calls_per_day": 5},
        {"id": "restricted-writer", "environment": "restricted", "ingress": "cloud", "model": "x-ai/grok-4.7",
         "routes": ["general-writing", "code"], "tiers": ["restricted-teaching", "restricted-explicit"],
         "default_tier": "restricted-teaching", "accounts": {"fetlife": ["read"]}, "project": "kink-courses",
         "expires": exp, "monthly_usd": 100},
        {"id": "trillian-local", "environment": "trillian", "ingress": "machine", "model": "qwen3:30b",
         "routes": ["general-writing", "local"], "tiers": ["open", "tier1"], "default_tier": "open",
         "accounts": {}, "project": "systems", "expires": exp, "monthly_usd": 100}]}
    tools = {"version": 1, "accounts": [
        {"account": "spotify", "tier": "open",
         "verbs": {"read": {"method": "GET", "base": "https://api.spotify.com/v1", "paths": ["/me/playlists", "/playlists/*"]}},
         "auth": {"header": "Authorization", "format": "Bearer {secret}", "secret": "SPOTIFY_TOKEN"}},
        {"account": "fetlife", "tier": "restricted-explicit",
         "verbs": {"read": {"method": "GET", "base": "https://api.fetlife.test", "paths": ["/me"]}},
         "auth": {"header": "Authorization", "format": "Bearer {secret}", "secret": "FETLIFE_TOKEN"}}]}
    approved = {"version": 1, "approved": [
        {"model": "anthropic/claude-sonnet-5.5", "account": "spotify", "verbs": ["read"], "card": "u2-test"},
        {"model": "x-ai/grok-4.7", "account": "fetlife", "verbs": ["read"], "card": "u2-test"}]}
    (cfg / "tokens.yaml").write_text(yaml.safe_dump(tokens))
    (cfg / "tools.yaml").write_text(yaml.safe_dump(tools))
    (cfg / "approved-models.yaml").write_text(yaml.safe_dump(approved))


@pytest.fixture
def setup(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(TABLES, cfg, ignore=shutil.ignore_patterns("*.md"))
    fixture_tables(cfg)
    canaries = tmp_path / "canaries.json"
    canaries.write_text(json.dumps({"r": {"marker_sha256": sha(CANARY)}}))
    env = {"OPENROUTER_API": "test-key", "GW_TOKEN_SHA256_PERSONAL_SONNET": sha(TOK),
           "GW_TOKEN_SHA256_RESTRICTED_WRITER": sha(RTOK), "GW_TOKEN_SHA256_TRILLIAN_LOCAL": sha(MTOK),
           "SPOTIFY_TOKEN": "spot-secret-value", "FETLIFE_TOKEN": "fl-secret",
           "GW_CANARIES_FILE": str(canaries), "GW_CF_TEAM_DOMAIN": TEAM, "GW_CF_AUD": AUD,
           "GW_SHARED_LOG": str(tmp_path / "log/calls.jsonl"), "GW_RESTRICTED_LOG": str(tmp_path / "rlog/calls.jsonl")}
    up = Upstream()

    def make(port=8641):
        app = create_app(cfg, tmp_path / "state", env=env, transport=httpx.MockTransport(up))
        app.state.gw.jwk_client = FakeJWKs()
        return TestClient(app, base_url=f"http://testserver:{port}")
    return make(), up, cfg, tmp_path, make


def chat(c, token=TOK, route="general-writing", headers=None, content="hello", body=None, jwt_cn="svc-personal"):
    h = {"Authorization": f"Bearer {token}", **(headers or {})}
    if c.base_url.port == 8641 and jwt_cn:
        h.setdefault("Cf-Access-Jwt-Assertion", access_jwt(jwt_cn))
    b = {"model": f"route:{route}", "messages": [{"role": "user", "content": content}], **(body or {})}
    return c.post("/v1/chat/completions", headers=h, json=b)


def tool(c, account="spotify", verb="read", token=TOK, path="/me/playlists", headers=None, jwt_cn="svc-personal"):
    h = {"Authorization": f"Bearer {token}", **(headers or {})}
    if c.base_url.port == 8641 and jwt_cn:
        h.setdefault("Cf-Access-Jwt-Assertion", access_jwt(jwt_cn))
    return c.post(f"/v1/tools/{account}/{verb}", headers=h, json={"path": path})


def log_lines(tmp, name="log"):
    p = tmp / name / "calls.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def calls(tmp):
    return [l for l in log_lines(tmp) if l["kind"] == "call"]


def machine(c):
    return TestClient(c.app, base_url="http://testserver:8640")


def reload(c):
    """What a restart does: load the candidate, keep last-known-good if it fails."""
    gw = c.app.state.gw
    ok, info = gw.reload()
    gw.canaries = gw.load_canaries()
    return ok, info


# --- tables -------------------------------------------------------------------
def test_shipped_tables_are_valid():
    pol.load(TABLES)


def test_policy_rejects_unsafe_tables():
    base = {f: yaml.safe_load((TABLES / f).read_text()) for f in pol.FILES}
    exp = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    tok = {"id": "x", "environment": "personal", "ingress": "cloud", "model": "m", "routes": ["code"],
           "tiers": ["open"], "default_tier": "open", "project": "p", "expires": exp, "monthly_usd": 5}
    cases = {
        "tier1 on hosted route": lambda r: r["routing.yaml"]["routes"][0]["tiers"].append("tier1"),
        "wildcard route": lambda r: r["tokens.yaml"]["tokens"].append({**tok, "routes": ["*"]}),
        "approval with no card": lambda r: r["approved-models.yaml"]["approved"].append(
            {"model": "m", "account": "nope", "verbs": ["read"]}),
        "NaN cap": lambda r: r["policy.yaml"].__setitem__("monthly_cap_usd", float("nan")),
        "expiry not a date": lambda r: r["tokens.yaml"]["tokens"].append({**tok, "expires": "never"}),
        "expiry too far": lambda r: r["tokens.yaml"]["tokens"].append({**tok, "expires": "2099-01-01"}),
        "tier1 in a cloud environment": lambda r: r["tokens.yaml"]["tokens"].append(
            {**tok, "tiers": ["open", "tier1"], "routes": ["local"]}),
        "restricted env with open tier": lambda r: r["tokens.yaml"]["tokens"].append({**tok, "environment": "restricted"}),
        "cloud env on machine ingress": lambda r: r["tokens.yaml"]["tokens"].append({**tok, "ingress": "machine"}),
        "duplicate token": lambda r: r["tokens.yaml"]["tokens"].extend([tok, tok]),
        "no token budget": lambda r: r["tokens.yaml"]["tokens"].append({k: v for k, v in tok.items() if k != "monthly_usd"}),
        "scalar table entry": lambda r: r["routing.yaml"].__setitem__("routes", [None]),
        "tool takes the provider key": lambda r: r["tools.yaml"]["accounts"].append(
            {"account": "a", "verbs": {"read": {"method": "GET", "base": "https://x", "paths": ["/"]}},
             "auth": {"header": "A", "format": "{secret}", "secret": "OPENROUTER_API"}}),
        "run with no owner": lambda r: r["approved-runs.yaml"]["runs"].append({"run": "r", "budget_usd": 5, "card": "c"}),
    }
    for name, mutate in cases.items():
        raw = json.loads(json.dumps(base, default=str))
        for f, k in [("tokens.yaml", "tokens"), ("approved-models.yaml", "approved"), ("tools.yaml", "accounts"),
                     ("approved-runs.yaml", "runs")]:
            raw[f][k] = raw[f].get(k) or []
        mutate(raw)
        assert pol._check(raw), name


def test_policy_load_never_crashes(tmp_path):
    cfg = tmp_path / "c"
    shutil.copytree(TABLES, cfg, ignore=shutil.ignore_patterns("*.md"))
    for text in ("tokens: [1, 2]\n", "just a string\n", "tokens: {a: 1}\n"):
        (cfg / "tokens.yaml").write_text(text)
        with pytest.raises(pol.PolicyError):
            pol.load(cfg)


# --- auth and listeners -------------------------------------------------------
def test_no_token_or_wrong_token_is_refused(setup):
    c, up, *_ = setup
    assert c.post("/v1/chat/completions", json={"model": "route:general-writing"}).status_code == 401
    assert chat(c, token="gw.personal-sonnet." + "x" * 43).status_code == 401
    assert chat(c, token="gw.personal-sonnet.short").status_code == 401
    assert chat(c, token="gw.nobody." + "x" * 43).status_code == 401
    assert up.calls == []


def test_cloud_listener_needs_a_valid_access_jwt(setup):
    c, up, *_ = setup
    assert chat(c, jwt_cn=None).status_code == 401
    assert chat(c, headers={"Cf-Access-Jwt-Assertion": access_jwt(aud="other")}).status_code == 401
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert chat(c, headers={"Cf-Access-Jwt-Assertion": access_jwt(key=other)}).status_code == 401
    assert chat(c, jwt_cn="svc-someone-else").status_code == 401  # bound to its own service token
    assert up.calls == []
    assert chat(c).status_code == 200


def test_tokens_only_work_on_their_own_listener(setup):
    c, up, _, _, make = setup
    m = make(8640)
    assert chat(m, token=TOK).status_code == 401              # cloud token on the machine port
    assert chat(c, token=MTOK, jwt_cn="x").status_code == 401  # machine token through the tunnel
    assert chat(m, token=MTOK).status_code == 200


def test_cloud_listener_without_access_config_refuses_everything(setup):
    c, *_ = setup
    c.app.state.gw.env = {k: v for k, v in c.app.state.gw.env.items() if k != "GW_CF_AUD"}
    assert chat(c).status_code == 401


def test_no_admin_endpoint_and_detail_only_on_machine_port(setup):
    c, *_ = setup
    m = machine(c)
    for client in (c, m):
        assert client.post("/admin/reload").status_code in (404, 405)
    assert set(c.get("/healthz").json()) == {"ok"}
    assert "digest" in m.get("/healthz").json()


# --- request shape --------------------------------------------------------------
def test_raw_model_names_and_unlisted_routes_are_refused(setup):
    c, up, *_ = setup
    assert chat(c, body={"model": "x-ai/grok-4.7"}).status_code == 400
    assert chat(c, route="rough-writing").status_code == 403
    assert up.calls == []


@pytest.mark.parametrize("field", ["models", "route", "provider", "plugins", "transforms", "user", "prediction"])
def test_upstream_routing_fields_are_refused(setup, field):
    c, up, *_ = setup
    r = chat(c, body={field: ["unapproved/model"] if field == "models" else {"x": 1}})
    assert r.status_code == 400 and up.calls == []


def test_non_object_body_is_400(setup):
    c, *_ = setup
    h = {"Authorization": f"Bearer {TOK}", "Cf-Access-Jwt-Assertion": access_jwt()}
    assert c.post("/v1/chat/completions", headers=h, json=[1, 2]).status_code == 400
    assert c.post("/v1/tools/spotify/read", headers=h, json=[1]).status_code == 400


def test_max_tokens_is_capped(setup):
    c, up, *_ = setup
    chat(c, body={"max_tokens": 10 ** 9})
    assert up.calls[-1][1]["max_tokens"] == 16000
    chat(c)
    assert up.calls[-1][1]["max_tokens"] == 16000


def test_streaming_refused(setup):
    c, *_ = setup
    assert chat(c, body={"stream": True}).status_code == 400


# --- calls, cost, fallback ----------------------------------------------------
def test_open_call_logs_exact_cost_and_no_text(setup):
    c, up, _, tmp, _ = setup
    r = chat(c, headers={"X-Title": "pre-trip check"}, content="secret plans")
    assert r.status_code == 200
    url, body, headers = up.calls[0]
    assert body["model"] == "anthropic/claude-sonnet-5.5"
    assert body["provider"] == {"zdr": True, "data_collection": "deny", "allow_fallbacks": False}
    assert headers["authorization"] == "Bearer test-key"
    line = calls(tmp)[-1]
    assert line["cost_kind"] == "exact" and line["cost_usd"] == 0.0012 and line["title"] == "pre-trip check"
    assert "secret plans" not in (tmp / "log/calls.jsonl").read_text()
    assert not (tmp / "rlog/calls.jsonl").exists()


def test_decline_falls_back_without_rewording_and_charges_both(setup):
    c, up, _, tmp, _ = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "content_filter", 2.0)
    r = chat(c, content="exact words")
    assert r.status_code == 200
    assert [b["model"] for _, b, _ in up.calls] == ["anthropic/claude-sonnet-5.5", "x-ai/grok-4.7"]
    assert up.calls[0][1]["messages"] == up.calls[1][1]["messages"]
    assert sum(l["cost_usd"] for l in calls(tmp)) == pytest.approx(2.0012)
    assert c.app.state.gw.ledger.total == pytest.approx(2.0012)


def test_all_declined_is_502(setup):
    c, up, *_ = setup
    up.script = {"anthropic/claude-sonnet-5.5": (403, None, None), "x-ai/grok-4.7": (451, None, None)}
    assert chat(c).status_code == 502
    assert c.app.state.gw.ledger.total == 0.0


def test_missing_cost_charges_the_reservation(setup):
    c, up, _, tmp, _ = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", None)
    for i in range(3):
        assert chat(c, headers={"X-Run-Id": f"m{i}"}).status_code == 200
    assert [l["cost_kind"] for l in calls(tmp)] == ["estimated"] * 3
    assert c.app.state.gw.ledger.total == pytest.approx(1.5)


def test_concurrent_calls_cannot_overshoot_caps(setup):
    c, up, *_ = setup
    gw = c.app.state.gw
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", 0.4)

    async def burst():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=c.app, client=("127.0.0.1", 1)),
                                     base_url="http://testserver:8641") as a:
            h = {"Authorization": f"Bearer {TOK}"}
            reqs = [a.post("/v1/chat/completions", headers={**h, "Cf-Access-Jwt-Assertion": access_jwt()},
                           json={"model": "route:general-writing", "messages": []}) for _ in range(40)]
            return await asyncio.gather(*reqs)
    res = asyncio.run(burst())
    ok = sum(r.status_code == 200 for r in res)
    assert 0 < ok <= 12 and max(gw.ledger.runs.values()) <= 5.0 + 1e-9


def test_run_budget_is_lifetime_and_per_token(setup):
    c, up, cfg, tmp, make = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", 2.0)
    h = {"X-Run-Id": "small"}
    # A call is admitted while spend plus its reservation fits; its exact cost can then land
    # past the limit by at most that one call's overrun. $4 + 0.50 fits, $6 + 0.50 doesn't.
    assert [chat(c, headers=h).status_code for _ in range(4)] == [200, 200, 200, 402]
    c2 = make()
    assert chat(c2, headers=h).status_code == 402       # survives a restart
    gw = c2.app.state.gw
    gw.ledger.month = "1999-01"
    gw.ledger.roll()
    assert chat(c2, headers=h).status_code == 402       # and a month boundary
    assert chat(c2, token=RTOK, headers=h).status_code == 200   # same name, other token: its own run


def test_calls_without_a_run_id_still_have_a_run_budget(setup):
    c, up, *_ = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", 2.0)
    codes = [chat(c).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and 402 in codes


def test_run_ids_are_validated_and_never_logged_raw(setup):
    c, up, _, tmp, _ = setup
    assert chat(c, headers={"X-Run-Id": "Explicit scene words"}).status_code == 400
    assert chat(c, headers={"X-Run-Id": "batch-7"}).status_code == 200
    assert "batch-7" not in (tmp / "log/calls.jsonl").read_text()


def test_run_gate_needs_an_approval_owned_by_the_token(setup):
    c, up, cfg, tmp, make = setup
    big = {"X-Run-Id": "big", "X-Run-Estimate-USD": "7"}
    assert chat(c, headers=big).status_code == 402
    assert chat(c, headers={"X-Run-Estimate-USD": "7"}).status_code == 402
    assert chat(c, headers={"X-Run-Estimate-USD": "nan"}).status_code == 402
    runs = {"version": 1, "runs": [{"run": "big", "token": "restricted-writer", "budget_usd": 8, "card": "u2-test"}]}
    (cfg / "approved-runs.yaml").write_text(yaml.safe_dump(runs))
    assert reload(c)[0]
    assert chat(c, headers=big).status_code == 402      # someone else's approval
    assert chat(c, token=RTOK, headers=big).status_code == 200


def test_token_monthly_budget(setup):
    c, up, *_ = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", 4.5)
    codes = [chat(c, headers={"X-Run-Id": f"r{i}"}).status_code for i in range(8)]
    assert codes.count(200) == 7 and codes[-1] == 402   # $30 token budget: 6 x 4.5 + 0.5 fits, 7 x 4.5 + 0.5 doesn't


def test_monthly_cap_alerts_and_refuses_and_survives_restart(setup):
    c, up, cfg, tmp, make = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", 4.5)
    for i in range(8):
        assert chat(c, token=RTOK, headers={"X-Run-Id": f"r{i}"}).status_code == 200   # $36
    assert chat(c, token=RTOK, headers={"X-Run-Id": "r9"}).status_code == 200      # $40.5 > cap? no: 36+0.5 <= 40
    assert chat(c, token=RTOK, headers={"X-Run-Id": "r10"}).status_code == 402
    alerts = [l["percent"] for l in log_lines(tmp) if l["kind"] == "alert"]
    assert alerts == [50, 80, 100]
    c2 = make()
    assert c2.app.state.gw.ledger.total == pytest.approx(40.5)
    assert chat(c2, token=RTOK, headers={"X-Run-Id": "r11"}).status_code == 402


def test_reservation_without_settlement_stays_charged(setup):
    c, up, cfg, tmp, make = setup
    with open(tmp / "log/calls.jsonl", "a") as f:
        f.write(json.dumps({"kind": "reserve", "rid": "lost", "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "token": "personal-sonnet", "run": "x", "amount": 0.5}) + "\n")
    assert make().app.state.gw.ledger.total == pytest.approx(0.5)


def test_unwritable_log_stops_hosted_calls(setup):
    c, up, *_ = setup
    c.app.state.gw.shared_log = pathlib.Path("/proc/nope/calls.jsonl")
    assert chat(c).status_code == 503
    assert up.calls == []


# --- tiers --------------------------------------------------------------------
def test_tier1_header_is_refused_for_hosted_routes(setup):
    c, up, _, tmp, make = setup
    r = chat(make(8640), token=MTOK, headers={"X-Tier": "tier1"})
    assert r.status_code == 403 and up.calls == []


@pytest.mark.parametrize("hdr", [
    {"X-Source-Path": "/home/scon/work/obsidian-personal/journal.md"},
    {"X-Source-Path": "/home/scon/work/Obsidian-Personal/journal.md"},
    {"X-Source-Path": "/home/scon/work/obsidian-personal"},
    {"X-Source-Path": "C:\\Users\\scon\\obsidian-personal\\x.md"},
    {"X-Source-Path": "/home/scon/work/%6Fbsidian-personal/x.md"},
    {"X-Source-Path": "/home/scon/work/vault/../obsidian-personal/x.md"},
    {"X-Source-Path": "/home/scon/journals/alice.md"},
    {"X-Source": "gmail"}, {"X-Source": "Gmail (MCP)"}, {"X-Source": "google_calendar"},
    {"X-Source": "drive"}, {"X-Source": "something-new"},
])
def test_tier1_sources_are_recognised(setup, hdr):
    c, up, *_ = setup
    assert chat(c, headers=hdr).status_code == 403     # an Open cloud token may never send Tier-1
    assert up.calls == []


def test_open_sources_pass(setup):
    c, *_ = setup
    assert chat(c, headers={"X-Source": "repo", "X-Source-Path": "/home/user/scon-system/README.md"}).status_code == 200


def test_tier1_goes_to_local_route_only(setup):
    c, up, _, tmp, make = setup
    r = chat(make(8640), token=MTOK, route="local", headers={"X-Tier": "tier1", "X-Title": "journal"})
    assert r.status_code == 200
    assert up.calls[0][0].startswith("http://100.78.161.123:11434/")
    assert "authorization" not in up.calls[0][2]
    line = calls(tmp)[-1]
    assert line["title"] is None and line["cost_kind"] == "flat"


def test_canary_is_refused_before_any_call_and_never_logged(setup):
    c, up, _, tmp, _ = setup
    assert chat(c, content=f"notes {CANARY} more").status_code == 451
    assert chat(c, headers={"X-Title": f"t {CANARY}"}).status_code == 451
    assert up.calls == []
    assert CANARY not in (tmp / "log/calls.jsonl").read_text()


def test_missing_canary_registry_fails_closed(setup):
    c, up, *_ = setup
    c.app.state.gw.canaries = set()
    assert chat(c).status_code == 503 and up.calls == []
    assert machine(c).get("/healthz").status_code == 503


def test_restricted_text_only_in_restricted_log(setup):
    c, up, _, tmp, _ = setup
    assert chat(c, token=RTOK, content="lesson draft text", headers={"X-Title": "scene words"}).status_code == 200
    shared = (tmp / "log/calls.jsonl").read_text()
    assert "lesson draft text" not in shared and "scene words" not in shared
    line = calls(tmp)[-1]
    assert line["badge"] == "restricted" and line["cost_kind"] == "exact" and line["title"] is None
    assert "lesson draft text" in (tmp / "rlog/calls.jsonl").read_text()


def test_restricted_token_cannot_downgrade_to_open_or_use_non_zdr(setup):
    c, up, *_ = setup
    assert chat(c, token=RTOK, route="code", headers={"X-Tier": "open"}).status_code == 403
    assert up.calls == []


def test_open_token_cannot_send_restricted(setup):
    c, *_ = setup
    assert chat(c, headers={"X-Tier": "restricted-explicit"}).status_code == 403


# --- tools --------------------------------------------------------------------
def test_tool_call_needs_grant_and_approved_model(setup):
    c, up, cfg, tmp, _ = setup
    r = tool(c)
    assert r.status_code == 200 and r.json()["status"] == 200
    assert up.calls[-1][2]["authorization"] == "Bearer spot-secret-value"
    assert tool(c, verb="act").status_code == 403
    assert tool(c, token=RTOK, jwt_cn="any").status_code == 403   # not granted spotify
    (cfg / "approved-models.yaml").write_text(yaml.safe_dump({"version": 1, "approved": []}))
    reload(c)
    assert tool(c).status_code == 403
    assert "spot-secret-value" not in (tmp / "log/calls.jsonl").read_text()


@pytest.mark.parametrize("path", ["/playlists/x/tracks", "/playlists/../me", "/playlists/%2e%2e%2fme",
                                  "/playlists/x%2Ftracks", "/playlists/x;y", "/playlists\\x", "/me/playlists?x=1",
                                  "/me/playlistsX", "playlists/x"])
def test_tool_paths_are_literal(setup, path):
    c, up, *_ = setup
    assert tool(c, path=path).status_code == 403
    assert not any("spotify" in u for u, _, _ in up.calls)


def test_tool_respects_tiers(setup):
    c, up, _, tmp, _ = setup
    assert tool(c, headers={"X-Source": "gmail"}).status_code == 403      # Tier-1 never goes to a tool
    r = tool(c, token=RTOK, account="fetlife", path="/me", jwt_cn="any")
    assert r.status_code == 200
    assert calls  # Restricted account: the path is not in the shared log
    assert [l["path"] for l in log_lines(tmp) if l["kind"] == "tool"][-1] is None


def test_tool_response_never_carries_the_credential(setup):
    c, up, *_ = setup
    up.tool_body = '{"error": "bad header Authorization: Bearer spot-secret-value"}'
    r = tool(c)
    assert "spot-secret-value" not in r.text and "[redacted]" in r.text


def test_tool_daily_limit(setup):
    c, *_ = setup
    codes = [tool(c).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


def test_tool_fails_closed_without_credential(setup):
    c, *_ = setup
    c.app.state.gw.env = {**c.app.state.gw.env, "SPOTIFY_TOKEN": ""}
    assert tool(c).status_code == 503


# --- policy lifecycle -----------------------------------------------------------
def test_bad_candidate_keeps_last_known_good(setup):
    c, up, cfg, tmp, make = setup
    m = machine(c)
    good = m.get("/healthz").json()["digest"]
    r = yaml.safe_load((cfg / "routing.yaml").read_text())
    r["routes"][0]["zdr"] = False  # general-writing carries restricted tiers: must be zdr
    (cfg / "routing.yaml").write_text(yaml.safe_dump(r))
    ok, problems = reload(c)
    assert not ok and "zdr" in json.dumps(problems)
    assert m.get("/healthz").json()["digest"] == good
    assert chat(c).status_code == 200
    h = machine(make()).get("/healthz").json()
    assert h["degraded"] is True and h["digest"] == good


def test_no_policy_at_all_fails_closed(tmp_path):
    c = TestClient(create_app(tmp_path / "empty", tmp_path / "state", env={"GW_SHARED_LOG": str(tmp_path / "l.jsonl")}),
                   base_url="http://testserver:8640")
    assert c.get("/healthz").status_code == 503
    assert chat(c, token=MTOK).status_code == 503


def test_path_helpers():
    assert path_ok("/playlists/abc", "/playlists/*")
    assert not path_ok("/playlists/abc/tracks", "/playlists/*")
    assert clean_path("/me/playlists") and not clean_path("/me/%2e")


def test_duplicate_control_headers_are_refused(setup):
    c, up, *_ = setup
    h = [("Authorization", f"Bearer {TOK}"), ("Cf-Access-Jwt-Assertion", access_jwt()),
         ("X-Source", "repo"), ("X-Source", "gmail")]
    r = c.post("/v1/chat/completions", headers=h, json={"model": "route:general-writing", "messages": []})
    assert r.status_code == 400 and up.calls == []


def test_tool_read_takes_no_body_and_only_listed_query_keys(setup):
    c, *_ = setup
    h = {"Authorization": f"Bearer {TOK}", "Cf-Access-Jwt-Assertion": access_jwt()}
    assert c.post("/v1/tools/spotify/read", headers=h, json={"path": "/me/playlists", "json": {"a": 1}}).status_code == 400
    assert c.post("/v1/tools/spotify/read", headers=h,
                  json={"path": "/me/playlists", "query": {"_method": "DELETE"}}).status_code == 403


def test_read_verbs_cannot_use_write_methods():
    raw = {f: yaml.safe_load((TABLES / f).read_text()) for f in pol.FILES}
    raw["tokens.yaml"]["tokens"] = raw["tokens.yaml"].get("tokens") or []
    raw["approved-models.yaml"]["approved"] = []
    raw["approved-runs.yaml"]["runs"] = []
    raw["tools.yaml"]["accounts"] = [{"account": "x", "verbs": {"read": {"method": "DELETE", "base": "https://x", "paths": ["/"]}},
                                      "auth": {"header": "A", "format": "{secret}", "secret": "X_TOKEN"}}]
    assert any("GET" in p for p in pol._check(raw))
