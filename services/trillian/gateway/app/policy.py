"""Load and check the gateway's tables (scon-system/gateway/*.yaml).

A policy is only ever used whole: every file parses and every rule below holds, or the
candidate is rejected and the last-known-good copy keeps serving (round 11 D7).

    python3 -m app.policy /path/to/scon-system/gateway     # exit 1 and list problems if bad
"""
import datetime, fnmatch, hashlib, json, pathlib, shutil, sys
import yaml

FILES = ["routing.yaml", "approved-models.yaml", "tools.yaml", "tokens.yaml", "policy.yaml", "approved-runs.yaml"]
TIERS = ["open", "restricted-teaching", "restricted-explicit", "tier1"]
RESTRICTED = {"restricted-teaching", "restricted-explicit"}
VERBS = {"read", "act"}
PROVIDERS = {"openrouter", "ollama"}


class PolicyError(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def rank(tier):
    return TIERS.index(tier)


class Policy:
    def __init__(self, raw, digest):
        self.raw, self.digest = raw, digest
        self.routes = {r["id"]: r for r in raw["routing.yaml"]["routes"]}
        self.tokens = {t["id"]: t for t in raw["tokens.yaml"]["tokens"]}
        self.accounts = {a["account"]: a for a in raw["tools.yaml"]["accounts"]}
        self.approved = raw["approved-models.yaml"]["approved"]
        self.runs = {r["run"]: r for r in raw["approved-runs.yaml"]["runs"]}
        self.limits = raw["policy.yaml"]

    def provider(self, route):
        return route.get("provider", "openrouter")

    def model_approved(self, model, account, verb):
        return any(e["model"] == model and e["account"] == account and verb in e["verbs"] for e in self.approved)

    def is_tier1_source(self, source_path, source):
        t1 = self.limits["tier1"]
        if source and source.strip().lower() in t1.get("sources", []):
            return True
        if source_path:
            p = "/" + source_path.strip().lstrip("/")
            return any(fnmatch.fnmatch(p, g) for g in t1.get("source_globs", []))
        return False


def _check(raw):
    bad = []
    routing = raw["routing.yaml"]
    for r in routing.get("routes", []):
        rid = r.get("id", "?")
        tiers = r.get("tiers", [])
        if not r.get("models"):
            bad.append(f"route {rid}: no models")
        if any(t not in TIERS for t in tiers):
            bad.append(f"route {rid}: unknown tier in {tiers}")
        prov = r.get("provider", "openrouter")
        if prov not in PROVIDERS:
            bad.append(f"route {rid}: unknown provider {prov}")
        if "tier1" in tiers and prov != "ollama":
            bad.append(f"route {rid}: tier1 on a non-local route")
        if RESTRICTED & set(tiers) and prov == "openrouter" and not r.get("zdr"):
            bad.append(f"route {rid}: carries a restricted tier without zdr")
    ids = [r.get("id") for r in routing.get("routes", [])]
    if len(ids) != len(set(ids)):
        bad.append("routing: duplicate route id")

    accounts = {a.get("account"): a for a in raw["tools.yaml"].get("accounts", [])}
    for name, a in accounts.items():
        if not set(a.get("verbs", {})) <= VERBS:
            bad.append(f"tool {name}: verbs must be read/act")
        if "{secret}" not in a.get("auth", {}).get("format", ""):
            bad.append(f"tool {name}: auth.format needs {{secret}}")
        for verb, v in a.get("verbs", {}).items():
            if not str(v.get("base", "")).startswith("https://"):
                bad.append(f"tool {name}.{verb}: base must be https")
            if not v.get("paths"):
                bad.append(f"tool {name}.{verb}: no paths (an empty list would allow nothing; say so explicitly by removing the verb)")

    for e in raw["approved-models.yaml"].get("approved", []):
        if e.get("account") not in accounts:
            bad.append(f"approved {e.get('model')}: unknown account {e.get('account')}")
        if not e.get("card"):
            bad.append(f"approved {e.get('model')}: no approving card")
        if not set(e.get("verbs", [])) <= VERBS:
            bad.append(f"approved {e.get('model')}: verbs must be read/act")

    route_ids = set(ids)
    for t in raw["tokens.yaml"].get("tokens", []):
        tid = t.get("id", "?")
        for k in ("environment", "model", "routes", "tiers", "default_tier", "project", "expires"):
            if k not in t:
                bad.append(f"token {tid}: missing {k}")
        if "*" in t.get("routes", []) or not set(t.get("routes", [])) <= route_ids:
            bad.append(f"token {tid}: routes must be named routes, no wildcard")
        if any(x not in TIERS for x in t.get("tiers", [])) or t.get("default_tier") not in t.get("tiers", []):
            bad.append(f"token {tid}: bad tiers or default_tier")
        for acct, verbs in (t.get("accounts") or {}).items():
            if acct not in accounts or not set(verbs) <= VERBS:
                bad.append(f"token {tid}: bad account grant {acct}")
        if not str(tid).replace("-", "").isalnum():
            bad.append(f"token {tid}: id must be letters, digits and dashes")

    lim = raw["policy.yaml"]
    for k in ("monthly_cap_usd", "run_gate_usd", "unapproved_run_spend_usd", "alerts_percent", "tier1", "logs"):
        if k not in lim:
            bad.append(f"policy: missing {k}")
    if lim.get("unapproved_run_spend_usd", 0) > lim.get("run_gate_usd", 0):
        bad.append("policy: unapproved_run_spend_usd above the run gate")
    for r in raw["approved-runs.yaml"].get("runs", []):
        if not r.get("card") or not isinstance(r.get("budget_usd"), (int, float)):
            bad.append(f"run {r.get('run')}: needs card and budget_usd")
    return bad


def load(config_dir):
    d = pathlib.Path(config_dir)
    raw, h, bad = {}, hashlib.sha256(), []
    for f in FILES:
        p = d / f
        if not p.exists():
            bad.append(f"{f}: missing")
            continue
        b = p.read_bytes()
        h.update(f.encode() + b"\0" + b)
        try:
            raw[f] = yaml.safe_load(b) or {}
        except yaml.YAMLError as e:
            bad.append(f"{f}: {e}")
    if bad:
        raise PolicyError(bad)
    for f, key in [("routing.yaml", "routes"), ("tokens.yaml", "tokens"), ("tools.yaml", "accounts"),
                   ("approved-models.yaml", "approved"), ("approved-runs.yaml", "runs")]:
        raw[f].setdefault(key, [])
        if not isinstance(raw[f][key], list):
            bad.append(f"{f}: {key} must be a list")
    if bad:
        raise PolicyError(bad)
    bad = _check(raw)
    if bad:
        raise PolicyError(bad)
    return Policy(raw, h.hexdigest()[:12])


def save_lkg(config_dir, state_dir):
    lkg = pathlib.Path(state_dir) / "lkg"
    tmp = pathlib.Path(state_dir) / "lkg.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for f in FILES:
        shutil.copy2(pathlib.Path(config_dir) / f, tmp / f)
    (tmp / "SAVED").write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
    shutil.rmtree(lkg, ignore_errors=True)
    tmp.rename(lkg)


if __name__ == "__main__":
    try:
        p = load(sys.argv[1])
    except PolicyError as e:
        print("\n".join(e.problems))
        sys.exit(1)
    print(json.dumps({"ok": True, "digest": p.digest, "routes": len(p.routes), "tokens": len(p.tokens),
                      "accounts": len(p.accounts), "approved": len(p.approved)}))
