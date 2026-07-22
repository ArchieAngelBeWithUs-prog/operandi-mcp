#!/usr/bin/env python3
"""OPERANDI MCP server — let ANY LLM-driven agent operate real appliances, natively.

"Build for agents": this exposes OPERANDI as Model Context Protocol tools over stdio, so a
Claude / GPT / Gemini agent (or a humanoid's planner) can, in its own tool loop:

  1. identify_appliance   — resolve what it's looking at (nameplate text / panel labels / model)
  2. get_operation_package — pull the grounded, safety-checked, robot-executable package for it
  3. list_appliances / find_by_capability — browse what OPERANDI can operate

The package is the value: model-exact procedures, control map + grounding (where each control is
and how it's actuated), per-step verification signals, a recovery state machine, and a safety
envelope — the per-appliance knowledge a general model measurably hallucinates without (Stage A:
24% of cold instructions were confidently wrong; grounded → 0). See docs/BUSINESS_MODEL.md.

Zero heavy deps: MCP stdio is newline-delimited JSON-RPC 2.0, implemented here with the stdlib
(+ `requests` for the REST call). It's a thin, API-key-authenticated client over the OPERANDI REST
API, so it works against a local dev server or the hosted service unchanged.

Config (env):
  OPERANDI_API_URL   base URL of the OPERANDI API (default https://api.operandi.cc)
  OPERANDI_API_KEY   your key (sent as `Authorization: Bearer <key>`)

Run (an agent host spawns this over stdio):
  OPERANDI_API_KEY=ok_live_... python mcp/operandi_mcp_server.py
"""
from __future__ import annotations

import json
import os
import sys

API_URL = os.environ.get("OPERANDI_API_URL", "https://api.operandi.cc").rstrip("/")
API_KEY = os.environ.get("OPERANDI_API_KEY", "")
SERVER_NAME = "operandi"
SERVER_VERSION = "1.0.1"
PROTOCOL_VERSION = "2025-06-18"

_KEY_CACHE = os.path.expanduser("~/.operandi/mcp_key")


def _ensure_key() -> str:
    """Zero-config first run: with no OPERANDI_API_KEY set, mint an INSTANT TRIAL key
    (POST /v1/trial — no signup, 2 packages included) and cache it, so an agent that
    just installed this server is answering questions seconds later. The API's 402
    afterwards explains the free/pro upgrade in-band."""
    global API_KEY
    if API_KEY:
        return API_KEY
    try:
        with open(_KEY_CACHE, encoding="utf-8") as fh:
            API_KEY = fh.read().strip()
            if API_KEY:
                return API_KEY
    except OSError:
        pass
    import json as _json
    import urllib.request
    try:
        req = urllib.request.Request(f"{API_URL}/v1/trial", data=b"", method="POST",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            API_KEY = _json.loads(resp.read()).get("api_key", "")
        if API_KEY:
            os.makedirs(os.path.dirname(_KEY_CACHE), exist_ok=True)
            with open(_KEY_CACHE, "w", encoding="utf-8") as fh:
                fh.write(API_KEY)
            try:
                os.chmod(_KEY_CACHE, 0o600)
            except OSError:
                pass
    except Exception:  # noqa: BLE001 — offline/miss just falls back to keyless calls
        API_KEY = ""
    return API_KEY

def _request(method: str, path: str, *, params=None, json_body=None) -> tuple[bool, dict | list | str]:
    """One REST call to the OPERANDI API via the stdlib (no deps — matches the SDK's zero-dep ethos,
    so `pip install operandi-mcp` drops into any runtime). Returns (ok, parsed_json_or_error)."""
    import json as _json
    import urllib.error
    import urllib.parse
    import urllib.request
    url = f"{API_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = _json.dumps(json_body).encode() if json_body is not None else None
    headers = {"Accept": "application/json"}
    if _ensure_key():
        headers["Authorization"] = f"Bearer {API_KEY}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return (False, "Unauthorized — set OPERANDI_API_KEY to a valid key "
                           "(or delete ~/.operandi/mcp_key to mint a fresh instant trial).")
        if exc.code == 402:
            detail = exc.read()[:300].decode("utf-8", "replace")
            return (False, f"Allowance used up. {detail} "
                           "Sign up free at POST {api}/v1/auth/signup (10 packages/month) or go Pro "
                           "via POST {api}/v1/billing/checkout.".replace("{api}", API_URL))
        if exc.code == 404:
            return (False, f"Not found: {path}")
        return (False, f"OPERANDI API error {exc.code}: {exc.read()[:300].decode('utf-8', 'replace')}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return (False, f"OPERANDI API unreachable at {url}: {exc}")
    try:
        return (True, _json.loads(body))
    except ValueError:
        return (False, "OPERANDI API returned non-JSON.")


# --- tool catalogue -------------------------------------------------------- #
TOOLS = [
    {
        "name": "identify_appliance",
        "description": (
            "Resolve which appliance an agent/robot is looking at, from observed text or panel "
            "labels, to an OPERANDI catalog object. Call this first, then get_operation_package "
            "with the returned slug. Returns ranked matches with confidence."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Observed nameplate / model text (e.g. 'Samsung ME20H705MSS')."},
                "category": {"type": "string",
                             "description": "Optional category hint, e.g. 'microwave_oven'."},
                "brand": {"type": "string", "description": "Optional brand hint if known."},
                "panel_labels": {"type": "array", "items": {"type": "string"},
                                 "description": "Optional control labels OCR'd off the panel "
                                                "(helps when the nameplate is hidden)."},
                "limit": {"type": "integer", "description": "Max matches (1-20, default 5)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_operation_package",
        "description": (
            "Get the robot-executable operation package for an appliance: model-exact ordered "
            "procedures, a control map with grounding (where each control is + how it is actuated), "
            "per-step verification signals, a recovery state machine, and a safety envelope "
            "(hazards / interlocks / never-do). This is the grounded knowledge a general model "
            "hallucinates without. Optionally target one procedure (e.g. 'defrost')."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string",
                        "description": "Catalog slug or model id from identify_appliance."},
                "procedure": {"type": "string",
                              "description": "Optional procedure name/id (default: the primary task)."},
            },
            "required": ["ref"],
        },
    },
    {
        "name": "list_appliances",
        "description": "Browse the appliances OPERANDI can operate, optionally filtered by category.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Optional category filter."},
                "limit": {"type": "integer", "description": "Max results (default 25)."},
            },
        },
    },
    {
        "name": "find_by_capability",
        "description": ("Find appliances by what they DO (e.g. 'heat', 'wash', 'brew', 'defrost') — "
                        "useful when an agent has a goal but not a specific model in mind."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "capability": {"type": "string",
                               "description": "A function tag, e.g. 'heat' / 'wash' / 'brew'."},
            },
            "required": ["capability"],
        },
    },
]

_TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


def _call_tool(name: str, args: dict) -> tuple[bool, dict | list | str]:
    args = args or {}
    if name == "identify_appliance":
        body = {"query": args.get("query", ""),
                "category": args.get("category"),
                "brand": args.get("brand"),
                "panel_labels": args.get("panel_labels"),
                "limit": int(args.get("limit", 5))}
        body = {k: v for k, v in body.items() if v is not None}
        return _request("POST", "/v1/identify", json_body=body)
    if name == "get_operation_package":
        ref = args.get("ref", "")
        params = {"procedure": args["procedure"]} if args.get("procedure") else None
        return _request("GET", f"/v1/operate/{ref}", params=params)
    if name == "list_appliances":
        params = {"limit": int(args.get("limit", 25))}
        if args.get("category"):
            params["category"] = args["category"]
        return _request("GET", "/v1/objects", params=params)
    if name == "find_by_capability":
        return _request("GET", f"/v1/capabilities/{args.get('capability', '')}")
    return (False, f"Unknown tool: {name}")


# --- JSON-RPC 2.0 (MCP stdio) --------------------------------------------- #
def _result(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(req: dict) -> dict | None:
    """Process one JSON-RPC request; return the response, or None for notifications."""
    method = req.get("method")
    req_id = req.get("id")
    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None                                   # notification — no reply
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        if name not in _TOOLS_BY_NAME:
            return _error(req_id, -32602, f"Unknown tool: {name}")
        ok, data = _call_tool(name, params.get("arguments") or {})
        text = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
        return _result(req_id, {
            "content": [{"type": "text", "text": text}],
            "isError": not ok,
        })
    if req_id is None:
        return None                                   # unknown notification — ignore
    return _error(req_id, -32601, f"Method not found: {method}")


def main() -> int:
    """Newline-delimited JSON-RPC over stdio (the MCP stdio transport)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
