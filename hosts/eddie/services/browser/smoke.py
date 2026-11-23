#!/usr/bin/env python3
"""Smoke test for eddie's browser: open https://example.com through the MCP server and
check the page arrived. Run on eddie: python3 smoke.py [http://127.0.0.1:8931/mcp]"""
# scon-fetch: local-only (talks to the MCP server on localhost; the page itself goes through the proxy)
import json
import sys
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8931/mcp"
session = None


def call(method, params=None, id_=1):
    global session
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if id_ is not None:
        body["id"] = id_
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(URL, json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=90) as r:
        session = r.headers.get("Mcp-Session-Id") or session
        text = r.read().decode()
    if id_ is None:
        return None
    for line in text.splitlines():          # SSE or plain JSON
        line = line[5:].strip() if line.startswith("data:") else line.strip()
        if line.startswith("{"):
            msg = json.loads(line)
            if msg.get("id") == id_:
                return msg
    raise SystemExit(f"no answer to {method}: {text[:300]}")


call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "eddie-smoke", "version": "1"}})
call("notifications/initialized", id_=None)
res = call("tools/call", {"name": "browser_navigate", "arguments": {"url": "https://example.com/"}}, 2)
out = json.dumps(res)
call("tools/call", {"name": "browser_close", "arguments": {}}, 3)
if "Example Domain" not in out:
    raise SystemExit(f"browser: page did not load: {out[:400]}")
print("browser: opened https://example.com through the scon-fetch proxy")
