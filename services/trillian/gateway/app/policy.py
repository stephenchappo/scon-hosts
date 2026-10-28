"""Load and check the gateway's tables (scon-system/gateway/*.yaml).

A policy is only ever used whole: every file parses and every rule below holds, or the
candidate is rejected and the last-known-good copy keeps serving (round 11 D7). Any
malformed input becomes a PolicyError, never a crash.

    python3 -m app.policy /path/to/scon-system/gateway     # exit 1 and list problems if bad
"""
import datetime, fnmatch, hashlib, json, math, os, pathlib, posixpath, re, shutil, sys, urllib.parse
import yaml

FILES = ["routing.yaml", "approved-models.yaml", "tools.yaml", "tokens.yaml", "policy.yaml", "approved-runs.yaml"]
TIERS = ["open", "restricted-teaching", "restricted-explicit", "tier1"]
RESTRICTED = {"restricted-teaching", "restricted-explicit"}
VERBS = {"read", "act"}
PROVIDERS = {"openrouter", "ollama"}
# Cloud environments may never carry Tier-1 (target design section 5); machines may, local route only.
CLOUD_ENVS = {"personal", "product", "restricted", "eval"}
MACHINE_ENVS = {"trillian", "deepthought", "anjie"}
INGRESS = {"machine", "cloud"}
RESERVED_SECRETS = re.compile(r"^(OPENROUTER_API.*|GW_.*|BWS_.*)$")
MAX_TOKEN_DAYS = 90
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class _UniqueLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise yaml.constructor.ConstructorError(None, None, f"duplicate key(s) {sorted(map(str, dup))}", node.start_mark)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)


def path_pattern_ok(p):
    """Policy path patterns follow the same literal rules the gateway applies to requests."""
    return (isinstance(p, str) and p.startswith("/") and "//" not in p
            and not re.search(r"[%;\\?#\s\x00-\x1f\x7f]", p)
            and all(seg not in {".", ".."} for seg in p.split("/")[1:]))


class PolicyError(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def rank(tier):
    return TIERS.index(tier)


def norm_source(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def canon_path(p):
    """Lowercase, forward slashes, percent-decoded (repeatedly), . and .. resolved."""
    p = p.strip()
    for _ in range(3):
        q = urllib.parse.unquote(p)
        if q == p:
            break
        p = q
    p = p.replace("\\", "/").lower()
    return posixpath.normpath("/" + p.lstrip("/"))


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
        """Header values are the caller's own claim (design risk 4); this only makes the claim hard to misspell."""
        t1 = self.limits["tier1"]
        if source is not None and source.strip():
            s = norm_source(source)
            if any(k in s for k in t1["source_keywords"]) or s not in {norm_source(x) for x in t1["open_sources"]}:
                return True
        if source_path:
            p = canon_path(source_path)
            if "%" in p:  # still encoded after decoding: can't be classified, so it is Tier-1
                return True
            for g in t1["source_globs"]:
                g = g.lower()
                if fnmatch.fnmatchcase(p, g) or fnmatch.fnmatchcase(p + "/", g) or fnmatch.fnmatchcase(p + "/x", g):
                    return True
        return False


def _money(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def _date(v):
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v))
    except ValueError:
        return None


def _check(raw, today=None):
    today = today or datetime.date.today()
    bad = []
    routing = raw["routing.yaml"]
    ids = []
    for r in routing["routes"]:
        if not isinstance(r, dict):
            bad.append("routing: every route must be a mapping")
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not ID.match(rid):
            bad.append(f"route {rid}: needs an id of lowercase letters, digits and dashes")
            continue
        ids.append(rid)
        if not isinstance(r.get("returns", []), list) or not all(isinstance(x, str) for x in r.get("returns", [])):
            bad.append(f"route {rid}: returns must be a list of model names")
        tiers = r.get("tiers") or []
        if not isinstance(r.get("models"), list) or not r["models"] or not all(isinstance(m, str) for m in r["models"]):
            bad.append(f"route {rid}: models must be a non-empty list of names")
        if not isinstance(tiers, list) or any(t not in TIERS for t in tiers):
            bad.append(f"route {rid}: unknown tier in {tiers}")
            tiers = []
        prov = r.get("provider", "openrouter")
        if prov not in PROVIDERS:
            bad.append(f"route {rid}: unknown provider {prov}")
        if "tier1" in tiers and prov != "ollama":
            bad.append(f"route {rid}: tier1 on a non-local route")
        if RESTRICTED & set(tiers) and prov == "openrouter" and r.get("zdr") is not True:
            bad.append(f"route {rid}: carries a restricted tier without zdr")
        if "reserve_usd" in r and not (_money(r["reserve_usd"]) and r["reserve_usd"] > 0):
            bad.append(f"route {rid}: reserve_usd must be a positive number")
    if len(ids) != len(set(ids)):
        bad.append("routing: duplicate route id")

    accounts = {}
    for a in raw["tools.yaml"]["accounts"]:
        if not isinstance(a, dict) or "account" not in a:
            bad.append("tools: every account needs a name")
            continue
        name = a["account"]
        if name in accounts:
            bad.append(f"tool {name}: duplicate account")
        accounts[name] = a
        if a.get("tier", "open") not in TIERS or a.get("tier") == "tier1":
            bad.append(f"tool {name}: tier must be open, restricted-teaching or restricted-explicit")
        auth = a.get("auth") if isinstance(a.get("auth"), dict) else {}
        if "{secret}" not in str(auth.get("format", "")) or not auth.get("header") or not auth.get("secret"):
            bad.append(f"tool {name}: auth needs header, secret and a format containing {{secret}}")
        elif RESERVED_SECRETS.match(str(auth["secret"])):
            bad.append(f"tool {name}: secret {auth['secret']} is reserved for the gateway itself")
        verbs = a.get("verbs") if isinstance(a.get("verbs"), dict) else {}
        if not verbs or not set(verbs) <= VERBS:
            bad.append(f"tool {name}: verbs must be read and/or act")
        for verb, v in verbs.items():
            v = v if isinstance(v, dict) else {}
            if v.get("method") not in ({"GET", "HEAD"} if verb == "read" else {"POST", "PUT", "PATCH", "DELETE"}):
                bad.append(f"tool {name}.{verb}: read is GET or HEAD only; act is POST, PUT, PATCH or DELETE")
            if not isinstance(v.get("query_keys", []), list):
                bad.append(f"tool {name}.{verb}: query_keys must be a list")
            if not str(v.get("base", "")).startswith("https://"):
                bad.append(f"tool {name}.{verb}: base must be https")
            if not isinstance(v.get("paths"), list) or not v["paths"] or not all(path_pattern_ok(x) for x in v["paths"]):
                bad.append(f"tool {name}.{verb}: paths must be literal /paths (one * per segment allowed)")
            if not all(isinstance(x, str) for x in v.get("query_keys", []) or []):
                bad.append(f"tool {name}.{verb}: query_keys must be names")

    for e in raw["approved-models.yaml"]["approved"]:
        if not isinstance(e, dict):
            bad.append("approved: every entry must be a mapping")
            continue
        if not isinstance(e.get("model"), str) or not e["model"]:
            bad.append("approved: every entry names a model")
        if e.get("account") not in accounts:
            bad.append(f"approved {e.get('model')}: unknown account {e.get('account')}")
        if not e.get("card"):
            bad.append(f"approved {e.get('model')}: no approving card")
        if not isinstance(e.get("verbs"), list) or not set(e["verbs"]) <= VERBS:
            bad.append(f"approved {e.get('model')}: verbs must be read/act")

    route_ids, tids = set(ids), []
    for t in raw["tokens.yaml"]["tokens"]:
        if not isinstance(t, dict):
            bad.append("tokens: every token must be a mapping")
            continue
        tid = str(t.get("id", "?"))
        tids.append(tid)
        miss = [k for k in ("environment", "ingress", "model", "routes", "tiers", "default_tier", "project",
                            "expires", "monthly_usd") if k not in t]
        if miss:
            bad.append(f"token {tid}: missing {miss}")
            continue
        if not ID.match(tid):
            bad.append(f"token {tid}: id must be lowercase letters, digits and dashes")
        env, tiers = t["environment"], t["tiers"]
        if env not in CLOUD_ENVS | MACHINE_ENVS:
            bad.append(f"token {tid}: unknown environment {env}")
        if t["ingress"] not in INGRESS or (env in CLOUD_ENVS) != (t["ingress"] == "cloud"):
            bad.append(f"token {tid}: ingress must be cloud for cloud environments and machine for machines")
        if not isinstance(t["routes"], list) or not set(t["routes"]) <= route_ids:
            bad.append(f"token {tid}: routes must be named routes, no wildcard")
        if not isinstance(tiers, list) or any(x not in TIERS for x in tiers) or t["default_tier"] not in tiers:
            bad.append(f"token {tid}: bad tiers or default_tier")
            tiers = []
        if "tier1" in tiers and env not in MACHINE_ENVS:
            bad.append(f"token {tid}: tier1 is never allowed in a cloud environment")
        if "tier1" in tiers and isinstance(t["routes"], list) and any(
                rr.get("provider", "openrouter") != "ollama" for rr in routing["routes"]
                if isinstance(rr, dict) and rr.get("id") in t["routes"]):
            bad.append(f"token {tid}: a token allowed tier1 may hold local routes only, so it can't claim Open "
                       "and reach a hosted route")
        if t["ingress"] == "cloud" and not (isinstance(t.get("access_client_id"), str) and t["access_client_id"]):
            bad.append(f"token {tid}: a cloud token must name its Cloudflare Access service token (access_client_id)")
        if env == "restricted" and any(x not in RESTRICTED for x in tiers):
            bad.append(f"token {tid}: a restricted-environment token carries restricted tiers only")
        if env != "restricted" and env in CLOUD_ENVS and RESTRICTED & set(tiers):
            bad.append(f"token {tid}: only the restricted environment may send restricted tiers")
        exp = _date(t["expires"])
        if exp is None:
            bad.append(f"token {tid}: expires must be a date (YYYY-MM-DD)")
        elif exp > today + datetime.timedelta(days=MAX_TOKEN_DAYS):
            bad.append(f"token {tid}: expires more than {MAX_TOKEN_DAYS} days out")
        if not (_money(t["monthly_usd"]) and t["monthly_usd"] > 0):
            bad.append(f"token {tid}: monthly_usd must be a positive number")
        if "tool_calls_per_day" in t and not (isinstance(t["tool_calls_per_day"], int) and t["tool_calls_per_day"] >= 0):
            bad.append(f"token {tid}: tool_calls_per_day must be a whole number")
        grants = t.get("accounts") or {}
        if not isinstance(grants, dict):
            bad.append(f"token {tid}: accounts must be a mapping")
            grants = {}
        for acct, verbs in grants.items():
            if acct not in accounts or not isinstance(verbs, list) or not set(verbs) <= VERBS:
                bad.append(f"token {tid}: bad account grant {acct}")
            elif accounts[acct].get("tier", "open") not in tiers:
                bad.append(f"token {tid}: account {acct} is {accounts[acct].get('tier')}, beyond the token's tiers")
    if len(tids) != len(set(tids)):
        bad.append("tokens: duplicate token id")

    lim = raw["policy.yaml"]
    for k in ("monthly_cap_usd", "run_gate_usd", "unapproved_run_spend_usd", "reserve_per_call_usd"):
        if not (_money(lim.get(k)) and lim.get(k) > 0):
            bad.append(f"policy: {k} must be a positive number")
    if not isinstance(lim.get("max_output_tokens"), int) or lim["max_output_tokens"] <= 0:
        bad.append("policy: max_output_tokens must be a positive whole number")
    if not isinstance(lim.get("alerts_percent"), list) or not all(_money(p) for p in lim["alerts_percent"]):
        bad.append("policy: alerts_percent must be a list of numbers")
    t1 = lim.get("tier1")
    if not isinstance(t1, dict) or not all(isinstance(t1.get(k), list) and all(isinstance(x, str) for x in t1[k])
                                           for k in ("source_globs", "source_keywords", "open_sources")):
        bad.append("policy: tier1 needs source_globs, source_keywords and open_sources lists of strings")
    logs = lim.get("logs")
    if not isinstance(logs, dict) or not isinstance(logs.get("shared"), str) or not isinstance(logs.get("restricted", ""), str):
        bad.append("policy: logs.shared (and logs.restricted, if set) must be paths")
    if _money(lim.get("unapproved_run_spend_usd")) and _money(lim.get("run_gate_usd")) and \
            lim["unapproved_run_spend_usd"] > lim["run_gate_usd"]:
        bad.append("policy: unapproved_run_spend_usd above the run gate")
    run_ids = [r.get("run") for r in raw["approved-runs.yaml"]["runs"] if isinstance(r, dict)]
    if len(run_ids) != len(set(run_ids)):
        bad.append("runs: duplicate run id")
    for r in raw["approved-runs.yaml"]["runs"]:
        if not isinstance(r, dict):
            bad.append("runs: every run must be a mapping")
            continue
        if not r.get("card") or not (_money(r.get("budget_usd")) and r["budget_usd"] > 0) or r.get("token") not in tids:
            bad.append(f"run {r.get('run')}: needs card, a positive budget_usd and the token it belongs to")
        if not re.match(r"^[a-z0-9][a-z0-9._-]{0,47}$", str(r.get("run", ""))):
            bad.append(f"run {r.get('run')}: run id must be lowercase letters, digits, dot, dash or underscore")
    return bad


def load(config_dir, today=None):
    d = pathlib.Path(config_dir)
    raw, h, bad = {}, hashlib.sha256(), []
    for f in FILES:
        p = d / f
        if not p.is_file():
            bad.append(f"{f}: missing")
            continue
        try:
            b = p.read_bytes()
        except OSError as e:
            bad.append(f"{f}: {e}")
            continue
        h.update(f.encode() + b"\0" + b)
        try:
            raw[f] = yaml.load(b, Loader=_UniqueLoader) or {}
        except yaml.YAMLError as e:
            bad.append(f"{f}: {e}")
            continue
        if not isinstance(raw[f], dict):
            bad.append(f"{f}: must be a mapping")
    if bad:
        raise PolicyError(bad)
    for f, key in [("routing.yaml", "routes"), ("tokens.yaml", "tokens"), ("tools.yaml", "accounts"),
                   ("approved-models.yaml", "approved"), ("approved-runs.yaml", "runs")]:
        raw[f].setdefault(key, [])
        if raw[f][key] is None:
            raw[f][key] = []
        if not isinstance(raw[f][key], list):
            bad.append(f"{f}: {key} must be a list")
    if bad:
        raise PolicyError(bad)
    try:
        bad = _check(raw, today)
    except Exception as e:  # a shape the checks didn't foresee is still a rejected candidate
        bad = [f"policy check crashed: {type(e).__name__}: {e}"]
    if bad:
        raise PolicyError(bad)
    try:
        return Policy(raw, h.hexdigest()[:12])
    except Exception as e:
        raise PolicyError([f"policy construction failed: {type(e).__name__}: {e}"])


def save_lkg(config_dir, state_dir, digest):
    """Copy the tables to an immutable lkg-<digest>/ and swap the `lkg` symlink to it atomically.
    The previous version is kept, so a crash mid-save never leaves no last-known-good."""
    state = pathlib.Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    target = state / f"lkg-{digest}"
    if not target.is_dir():
        tmp = state / f"lkg-{digest}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        for f in FILES:
            shutil.copy2(pathlib.Path(config_dir) / f, tmp / f)
        (tmp / "SAVED").write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
        tmp.rename(target)
    link, prev = state / "lkg", None
    if link.is_symlink():
        prev = os.readlink(link)
    if prev != target.name:
        tmp_link = state / "lkg.new"
        if tmp_link.is_symlink() or tmp_link.exists():
            tmp_link.unlink()
        tmp_link.symlink_to(target.name)
        os.replace(tmp_link, link)
    keep = {target.name, prev}
    for d in state.glob("lkg-*"):
        if d.name not in keep and not d.name.endswith(".tmp"):
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    try:
        p = load(sys.argv[1])
    except PolicyError as e:
        print("\n".join(e.problems))
        sys.exit(1)
    print(json.dumps({"ok": True, "digest": p.digest, "routes": len(p.routes), "tokens": len(p.tokens),
                      "accounts": len(p.accounts), "approved": len(p.approved)}))
