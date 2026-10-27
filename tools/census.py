#!/usr/bin/env python3
"""Read-only machine census for greenfield build step 4.

Run on each host:  python3 tools/census.py > census/<host>.json
Prints facts only: hardware, addresses, services, schedules, Claude Code setup.
Never prints environment values, file contents of secrets, or tokens. Anything
that looks like a credential in a cron line or unit file is replaced with [REDACTED].
"""
import json, os, platform, re, shutil, socket, subprocess, pathlib, datetime

SECRET = re.compile(r"(?i)((?:token|key|secret|password|passwd|pat|auth)[A-Za-z_]*\s*[=:]\s*)\S+|(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_\S+|xox[bp]-\S+|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.\S+)")
def red(s): return SECRET.sub(lambda m: (m.group(1) or "") + "[REDACTED]", s)
def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return ""
def lines(cmd): return [red(l) for l in run(cmd).splitlines() if l.strip()]
home = pathlib.Path.home()

c = {"host": socket.gethostname(), "taken": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
c["os"] = run(". /etc/os-release 2>/dev/null && echo $PRETTY_NAME") or platform.platform()
c["kernel"] = platform.release()
c["cpu"] = run("lscpu 2>/dev/null | sed -n 's/^Model name:\\s*//p' | head -1") or run("sysctl -n machdep.cpu.brand_string 2>/dev/null")
c["cores"] = os.cpu_count()
c["ram_gb"] = round(int(run("awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null") or 0) / 1048576, 1)
c["gpu"] = lines("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null")
c["disks"] = lines("df -h -x tmpfs -x devtmpfs -x overlay -x squashfs --output=target,size,used,pcent 2>/dev/null | tail -n +2")
c["addresses"] = lines("ip -4 -o addr show 2>/dev/null | awk '{print $2\" \"$4}' | grep -v '^lo '")
c["tailscale"] = {"ip": run("tailscale ip -4 2>/dev/null"), "name": run("tailscale status --self --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"Self\"][\"DNSName\"])' 2>/dev/null")}
c["listening"] = lines("ss -ltnH 2>/dev/null | awk '{print $4}' | sort -u")
c["docker"] = [dict(zip(["name", "image", "status", "ports"], l.split("\t"))) for l in lines("docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null")]
c["compose_projects"] = lines("docker compose ls -a --format json 2>/dev/null | python3 -c 'import json,sys;[print(p[\"Name\"],p[\"ConfigFiles\"]) for p in json.load(sys.stdin)]' 2>/dev/null")
c["systemd_user_units"] = lines("systemctl --user list-units --type=service,timer,path --all --no-legend --plain 2>/dev/null | awk '{print $1\" \"$3\" \"$4}'")
c["systemd_user_timers"] = lines("systemctl --user list-timers --all --no-legend 2>/dev/null")
c["systemd_system_custom"] = lines("ls /etc/systemd/system/*.service /etc/systemd/system/*.timer 2>/dev/null | xargs -n1 basename")
c["crontab"] = [l for l in lines("crontab -l 2>/dev/null") if not l.lstrip().startswith("#")]
c["claude_code"] = {"version": run("claude --version 2>/dev/null"), "path": shutil.which("claude")}
mcp = home / ".claude.json"
try:
    j = json.loads(mcp.read_text())
    servers = set(j.get("mcpServers", {}))
    for p in j.get("projects", {}).values(): servers |= set(p.get("mcpServers", {}))
    c["claude_mcp_servers"] = sorted(servers)
except Exception:
    c["claude_mcp_servers"] = []
try:
    s = json.loads((home / ".claude/settings.json").read_text())
    c["claude_hooks"] = {ev: [h.get("command", "") for g in v for h in g.get("hooks", [])] for ev, v in s.get("hooks", {}).items()}
except Exception:
    c["claude_hooks"] = {}
c["claude_skills"] = sorted(p.name for p in (home / ".claude/skills").glob("*")) if (home / ".claude/skills").exists() else []
c["claude_memory_dirs"] = sorted(p.parent.name for p in (home / ".claude/projects").glob("*/memory"))
c["work_repos"] = sorted(p.parent.name for p in (home / "work").glob("*/.git"))
print(json.dumps(c, indent=1))
