# OPERANDI MCP Server — operate real appliances from any agent

`operandi_mcp_server.py` exposes OPERANDI over the **Model Context Protocol** so any MCP-capable
agent host (Claude Desktop, Claude Code, or your own agent runtime) can identify an appliance and
pull its grounded, safety-checked, robot-executable operation package **as native tools**.

This is the "build for agents" surface: the customer is a robot's planner / an LLM agent, not a
human reading PDFs.

## Tools

| Tool | What it does |
|---|---|
| `identify_appliance` | Resolve observed nameplate text / panel labels / model → a catalog object (call first). |
| `get_operation_package` | The robot-executable package: model-exact procedures, control map + grounding, per-step verification signals, recovery state machine, safety envelope. |
| `list_appliances` | Browse operable appliances (optionally by category). |
| `find_by_capability` | Find appliances by function (`heat` / `wash` / `brew` / `defrost` …). |

## Why an agent wants this
A general model, cold, gives confidently-wrong physical instructions on ordinary appliances a large
fraction of the time (OPERANDI Stage A: **24% of cold instructions were would-fail**, including
invented buttons and cycles). Grounded in the package these tools return, that fell to **0
hallucinations, 96% exact**. The tools turn "guess the buttons" into "read the manufacturer's ground
truth". See `../docs/BUSINESS_MODEL.md`.

## Setup

No SDK to install — the server is stdlib JSON-RPC over stdio (uses `requests`, already present).
Point it at a running OPERANDI API and give it a key:

```bash
export OPERANDI_API_URL=https://api.operandi.example   # or https://api.operandi.cc for local dev
export OPERANDI_API_KEY=ok_live_...                     # from the dev portal / /v1/keys
python mcp/operandi_mcp_server.py                        # an MCP host spawns this over stdio
```

### Claude Desktop / Claude Code config
Add to your MCP servers config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "operandi": {
      "command": "python",
      "args": ["/Users/archieshouse/Operandi/mcp/operandi_mcp_server.py"],
      "env": {
        "OPERANDI_API_URL": "https://api.operandi.cc",
        "OPERANDI_API_KEY": "ok_live_your_key_here"
      }
    }
  }
}
```

Then ask the agent: *"Identify the Samsung ME20H705MSS and give me the safe procedure to defrost
0.5 kg of mince."* — it will call `identify_appliance` then `get_operation_package` and answer from
grounded data.

## Notes
- The server is a thin, API-key-authenticated REST client — the same binary works against local dev
  or the hosted service by changing `OPERANDI_API_URL`.
- Auth is `Authorization: Bearer <key>`; a missing/invalid key surfaces as a tool error, not a crash.
- Transport is newline-delimited JSON-RPC 2.0 (the MCP stdio transport). Offline protocol tests:
  `pytest tests/test_mcp_server.py`.
