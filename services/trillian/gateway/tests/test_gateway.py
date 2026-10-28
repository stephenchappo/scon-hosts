"""Gateway tests. No network: every upstream is an httpx.MockTransport.

Run: GATEWAY_TABLES=~/work/scon-system/gateway python3 -m pytest -q tests
(the tables default to ../../../../scon-system/gateway next to this repo).
"""
import hashlib, json, os, pathlib, shutil

import httpx, pytest, yaml
from fastapi.testclient import TestClient

from app import policy as pol
from app.gateway import create_app, path_ok

HERE = pathlib.Path(__file__).resolve().parent
TABLES = pathlib.Path(os.environ.get("GATEWAY_TABLES") or HERE.parents[4] / "scon-system" / "gateway")
TOK = "gw.personal-sonnet.s3cret-for-tests"
RTOK = "gw.restricted-writer.another-test-token"
CANARY = "CANARY-RS-123456"


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Upstream:
    """Records calls; answers per model from a script of (status, finish_reason, cost)."""

    def __init__(self):
        self.calls, self.script = [], {}

    def __call__(self, request):
        body = json.loads(request.content or b"{}")
        self.calls.append((str(request.url), body, dict(request.headers)))
        if "api.spotify.com" in str(request.url):
            return httpx.Response(200, text='{"items": []}')
        status, finish, cost = self.script.get(body.get("model"), (200, "stop", 0.0012))
        if status != 200:
            return httpx.Response(status, json={"error": {"code": status}})
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        if cost is not None:
            usage["cost"] = cost
        return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": {"content": "hi"}}],
                                         "usage": usage, "model": body.get("model")})


@pytest.fixture
def setup(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(TABLES, cfg, ignore=shutil.ignore_patterns("*.md"))
    tokens = {"version": 1, "tokens": [
        {"id": "personal-sonnet", "environment": "personal", "model": "anthropic/claude-sonnet-5.5",
         "routes": ["general-writing", "code", "local"], "tiers": ["open"], "default_tier": "open",
         "accounts": {"spotify": ["read"]}, "project": "personal", "expires": "2099-01-01"},
        {"id": "restricted-writer", "environment": "restricted", "model": "x-ai/grok-4.7",
         "routes": ["general-writing", "code", "local"], "tiers": ["restricted-teaching", "restricted-explicit", "tier1"],
         "default_tier": "restricted-teaching", "accounts": {}, "project": "kink-courses", "expires": "2099-01-01"}]}
    tools = {"version": 1, "accounts": [{"account": "spotify", "tier": "open",
             "verbs": {"read": {"method": "GET", "base": "https://api.spotify.com/v1", "paths": ["/me/playlists", "/playlists/*"]}},
             "auth": {"header": "Authorization", "format": "Bearer {secret}", "secret": "SPOTIFY_TOKEN"}}]}
    (cfg / "tokens.yaml").write_text(yaml.safe_dump(tokens))
    (cfg / "tools.yaml").write_text(yaml.safe_dump(tools))
    canaries = tmp_path / "canaries.json"
    canaries.write_text(json.dumps({"r": {"marker_sha256": sha(CANARY)}}))
    env = {"OPENROUTER_API": "test-key", "GW_TOKEN_SHA256_PERSONAL_SONNET": sha(TOK),
           "GW_TOKEN_SHA256_RESTRICTED_WRITER": sha(RTOK), "GW_ADMIN_SHA256": sha("admin"),
           "SPOTIFY_TOKEN": "spot", "GW_CANARIES_FILE": str(canaries),
           "GW_SHARED_LOG": str(tmp_path / "log/calls.jsonl"), "GW_RESTRICTED_LOG": str(tmp_path / "rlog/calls.jsonl")}
    up = Upstream()

    def make():
        return TestClient(create_app(cfg, tmp_path / "state", env=env, transport=httpx.MockTransport(up)))
    return make(), up, cfg, tmp_path, make


def chat(c, token=TOK, route="general-writing", headers=None, content="hello"):
    h = {"Authorization": f"Bearer {token}", **(headers or {})}
    return c.post("/v1/chat/completions", headers=h,
                  json={"model": f"route:{route}", "messages": [{"role": "user", "content": content}]})


def log_lines(tmp, name="log"):
    p = tmp / name / "calls.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def test_shipped_tables_are_valid():
    p = pol.load(TABLES)
    assert p.tokens == {} and p.approved == [] and p.accounts == {}, "seeded empty: deny by default"


def test_no_token_or_wrong_token_is_refused(setup):
    c, up, *_ = setup
    assert c.post("/v1/chat/completions", json={"model": "route:general-writing"}).status_code == 401
    assert chat(c, token="gw.personal-sonnet.wrong").status_code == 401
    assert chat(c, token="gw.nobody.x").status_code == 401
    assert up.calls == []


def test_raw_model_names_and_unlisted_routes_are_refused(setup):
    c, up, *_ = setup
    r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {TOK}"},
               json={"model": "x-ai/grok-4.7", "messages": []})
    assert r.status_code == 400
    assert chat(c, route="rough-writing").status_code == 403
    assert up.calls == []


def test_open_call_logs_exact_cost_and_no_text(setup):
    c, up, _, tmp, _ = setup
    r = chat(c, headers={"X-Title": "pre-trip check"}, content="secret plans")
    assert r.status_code == 200
    url, body, headers = up.calls[0]
    assert body["model"] == "anthropic/claude-sonnet-5.5"
    assert body["provider"] == {"zdr": True, "data_collection": "deny", "allow_fallbacks": True}
    assert headers["authorization"] == "Bearer test-key"
    line = log_lines(tmp)[-1]
    assert line["cost_kind"] == "exact" and line["cost_usd"] == 0.0012 and line["title"] == "pre-trip check"
    assert "secret plans" not in (tmp / "log/calls.jsonl").read_text()
    assert not (tmp / "rlog/calls.jsonl").exists()


def test_caller_cannot_override_provider_preferences(setup):
    c, up, *_ = setup
    c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {TOK}"},
           json={"model": "route:general-writing", "messages": [], "provider": {"data_collection": "allow"}})
    assert up.calls[0][1]["provider"]["data_collection"] == "deny"


def test_decline_falls_back_without_rewording(setup):
    c, up, _, tmp, _ = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "content_filter", 0.0)
    r = chat(c, content="exact words")
    assert r.status_code == 200
    assert [b["model"] for _, b, _ in up.calls] == ["anthropic/claude-sonnet-5.5", "x-ai/grok-4.7"]
    assert up.calls[0][1]["messages"] == up.calls[1][1]["messages"]
    assert log_lines(tmp)[-1]["fallbacks"] == 1


def test_all_declined_is_502(setup):
    c, up, *_ = setup
    up.script = {"anthropic/claude-sonnet-5.5": (403, None, None), "x-ai/grok-4.7": (451, None, None)}
    assert chat(c).status_code == 502


def test_tier1_header_is_refused_for_hosted_routes(setup):
    c, up, _, tmp, _ = setup
    r = chat(c, token=RTOK, headers={"X-Tier": "tier1"})
    assert r.status_code == 403 and up.calls == []
    assert log_lines(tmp)[-1]["status"] == "refused-tier1"


def test_tier1_source_path_and_google_source_force_tier1(setup):
    c, up, *_ = setup
    assert chat(c, token=RTOK, headers={"X-Source-Path": "/home/scon/work/obsidian-personal/journal.md"}).status_code == 403
    assert chat(c, token=RTOK, headers={"X-Source": "gmail"}).status_code == 403
    # an Open token can't send Tier-1 at all, even to the local route
    assert chat(c, route="local", headers={"X-Source": "gmail"}).status_code == 403
    assert up.calls == []


def test_tier1_goes_to_local_route_only(setup):
    c, up, _, tmp, _ = setup
    r = chat(c, token=RTOK, route="local", headers={"X-Tier": "tier1", "X-Title": "journal"})
    assert r.status_code == 200
    assert up.calls[0][0].startswith("http://deepthought:11434/")
    assert "authorization" not in up.calls[0][2]
    line = log_lines(tmp)[-1]
    assert line["title"] is None and line["cost_kind"] == "flat"


def test_canary_is_refused_before_any_call(setup):
    c, up, _, tmp, _ = setup
    r = chat(c, content=f"notes {CANARY} more")
    assert r.status_code == 451 and up.calls == []
    assert CANARY not in (tmp / "log/calls.jsonl").read_text()


def test_restricted_text_only_in_restricted_log(setup):
    c, up, _, tmp, _ = setup
    assert chat(c, token=RTOK, content="lesson draft text").status_code == 200
    shared = (tmp / "log/calls.jsonl").read_text()
    assert "lesson draft text" not in shared
    line = log_lines(tmp)[-1]
    assert line["badge"] == "restricted" and line["cost_kind"] == "exact"
    assert "lesson draft text" in (tmp / "rlog/calls.jsonl").read_text()


def test_restricted_token_cannot_downgrade_to_open_or_use_non_zdr(setup):
    c, up, *_ = setup
    # header says open, but the token's default is restricted-teaching, so the tier stays restricted
    assert chat(c, token=RTOK, route="code", headers={"X-Tier": "open"}).status_code == 403
    assert up.calls == []


def test_open_token_cannot_send_restricted(setup):
    c, up, *_ = setup
    assert chat(c, headers={"X-Tier": "restricted-explicit"}).status_code == 403


def test_run_gate_and_run_budget(setup):
    c, up, cfg, tmp, make = setup
    assert chat(c, headers={"X-Run-Id": "big", "X-Run-Estimate-USD": "7"}).status_code == 402
    assert chat(c, headers={"X-Run-Estimate-USD": "7"}).status_code == 402
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", 3.0)
    assert chat(c, headers={"X-Run-Id": "small"}).status_code == 200
    assert chat(c, headers={"X-Run-Id": "small"}).status_code == 200
    assert chat(c, headers={"X-Run-Id": "small"}).status_code == 402  # $6 spent > $5 unapproved
    runs = {"version": 1, "runs": [{"run": "big", "budget_usd": 8, "card": "u2-test"}]}
    (cfg / "approved-runs.yaml").write_text(yaml.safe_dump(runs))
    assert c.post("/admin/reload", headers={"Authorization": "Bearer admin"}).status_code == 200
    assert chat(c, headers={"X-Run-Id": "big", "X-Run-Estimate-USD": "7"}).status_code == 200


def test_monthly_cap_alerts_and_refuses_and_survives_restart(setup):
    c, up, cfg, tmp, make = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", 25.0)
    assert chat(c).status_code == 200  # 25 of 40: 50% alert
    assert chat(c).status_code == 200  # 50 of 40: 80% and 100%
    assert chat(c).status_code == 402
    alerts = [l["percent"] for l in log_lines(tmp) if l["kind"] == "alert"]
    assert alerts == [50, 80, 100]
    c2 = make()
    assert chat(c2).status_code == 402
    assert c2.get("/healthz").json()["month_usd"] == 50.0


def test_missing_cost_is_flagged_not_hidden(setup):
    c, up, _, tmp, _ = setup
    up.script["anthropic/claude-sonnet-5.5"] = (200, "stop", None)
    assert chat(c).status_code == 200
    assert log_lines(tmp)[-1]["cost_kind"] == "missing"


def test_streaming_refused(setup):
    c, *_ = setup
    r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {TOK}"},
               json={"model": "route:general-writing", "messages": [], "stream": True})
    assert r.status_code == 400


def test_tool_call_needs_grant_and_approved_model(setup):
    c, up, cfg, tmp, _ = setup
    h = {"Authorization": f"Bearer {TOK}"}
    assert c.post("/v1/tools/spotify/read", headers=h, json={"path": "/me/playlists"}).status_code == 403
    approved = {"version": 1, "approved": [{"model": "anthropic/claude-sonnet-5.5", "account": "spotify",
                                            "verbs": ["read"], "card": "u2-test", "added": "2026-10-28"}]}
    (cfg / "approved-models.yaml").write_text(yaml.safe_dump(approved))
    c.post("/admin/reload", headers={"Authorization": "Bearer admin"})
    r = c.post("/v1/tools/spotify/read", headers=h, json={"path": "/me/playlists"})
    assert r.status_code == 200 and r.json()["status"] == 200
    assert up.calls[-1][2]["authorization"] == "Bearer spot"
    assert c.post("/v1/tools/spotify/act", headers=h, json={"path": "/me/playlists"}).status_code == 403
    assert c.post("/v1/tools/spotify/read", headers=h, json={"path": "/playlists/x/tracks"}).status_code == 403
    assert c.post("/v1/tools/spotify/read", headers=h, json={"path": "/playlists/../me"}).status_code == 403
    assert c.post("/v1/tools/spotify/read", headers={"Authorization": f"Bearer {RTOK}"},
                  json={"path": "/me/playlists"}).status_code == 403
    assert "spot" not in (tmp / "log/calls.jsonl").read_text().replace("spotify", "")


def test_tool_fails_closed_without_credential(setup):
    c, up, cfg, tmp, make = setup
    approved = {"version": 1, "approved": [{"model": "anthropic/claude-sonnet-5.5", "account": "spotify",
                                            "verbs": ["read"], "card": "u2-test"}]}
    (cfg / "approved-models.yaml").write_text(yaml.safe_dump(approved))
    c.post("/admin/reload", headers={"Authorization": "Bearer admin"})
    c.app.state.gw.env = {**c.app.state.gw.env, "SPOTIFY_TOKEN": ""}
    assert c.post("/v1/tools/spotify/read", headers={"Authorization": f"Bearer {TOK}"},
                  json={"path": "/me/playlists"}).status_code == 503


def test_bad_candidate_keeps_last_known_good(setup):
    c, up, cfg, tmp, make = setup
    good = c.get("/healthz").json()["digest"]
    r = yaml.safe_load((cfg / "routing.yaml").read_text())
    r["routes"][0]["zdr"] = False  # general-writing carries restricted tiers: must be zdr
    (cfg / "routing.yaml").write_text(yaml.safe_dump(r))
    res = c.post("/admin/reload", headers={"Authorization": "Bearer admin"})
    assert res.status_code == 422 and "zdr" in json.dumps(res.json())
    assert c.get("/healthz").json()["digest"] == good
    assert chat(c).status_code == 200
    # a restart with the bad candidate serves the last-known-good copy, marked degraded
    h = make().get("/healthz").json()
    assert h["degraded"] is True and h["digest"] == good


def test_no_policy_at_all_fails_closed(tmp_path):
    c = TestClient(create_app(tmp_path / "empty", tmp_path / "state", env={"GW_SHARED_LOG": str(tmp_path / "l.jsonl")}))
    assert c.get("/healthz").status_code == 503
    assert chat(c).status_code == 503


def test_reload_needs_admin(setup):
    c, *_ = setup
    assert c.post("/admin/reload").status_code == 401
    assert c.post("/admin/reload", headers={"Authorization": f"Bearer {TOK}"}).status_code == 401


def test_policy_checks():
    raw_bad = [
        ("tier1 on hosted", lambda r: r["routing.yaml"]["routes"][0]["tiers"].append("tier1")),
        ("wildcard route", lambda r: r["tokens.yaml"]["tokens"].append(
            {"id": "x", "environment": "e", "model": "m", "routes": ["*"], "tiers": ["open"],
             "default_tier": "open", "project": "p", "expires": "2099-01-01"})),
        ("approval with no card", lambda r: r["approved-models.yaml"]["approved"].append(
            {"model": "m", "account": "nope", "verbs": ["read"]})),
    ]
    base = {f: yaml.safe_load((TABLES / f).read_text()) for f in pol.FILES}
    for name, mutate in raw_bad:
        raw = json.loads(json.dumps(base))
        for f, k in [("tokens.yaml", "tokens"), ("approved-models.yaml", "approved")]:
            raw[f][k] = raw[f].get(k) or []
        mutate(raw)
        assert pol._check(raw), name


def test_path_glob_is_one_segment():
    assert path_ok("/playlists/abc", "/playlists/*")
    assert not path_ok("/playlists/abc/tracks", "/playlists/*")
    assert not path_ok("/me/playlistsX", "/me/playlists")
