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

## Setup — zero config

```bash
pip install operandi-mcp
```

That's it. **No key needed for your first packages**: on first use the server mints an
instant trial key itself (`POST /v1/trial` — no signup, 2 operation packages included,
cached at `~/.operandi/mcp_key`). When the trial is spent, tool responses tell the agent
exactly how to sign up free (10 packages/month) or go Pro.

Have a key already? Set it and it wins over the trial:

```bash
export OPERANDI_API_KEY=ok_live_...
```

### Claude Desktop / Claude Code config

```json
{
  "mcpServers": {
    "operandi": { "command": "operandi-mcp" }
  }
}
```

(Optionally add `"env": {"OPERANDI_API_KEY": "ok_live_..."}` once you have an account key.)

Then ask the agent: *"Identify the Samsung ME20H705MSS and give me the safe procedure to defrost
0.5 kg of mince."* — it will call `identify_appliance` then `get_operation_package` and answer from
grounded data.

## Notes
- The server is a thin, API-key-authenticated REST client — the same binary works against local dev
  or the hosted service by changing `OPERANDI_API_URL`.
- Auth is `Authorization: Bearer <key>`; a missing/invalid key surfaces as a tool error, not a crash.
- Transport is newline-delimited JSON-RPC 2.0 (the MCP stdio transport). Offline protocol tests:
  `pytest tests/test_mcp_server.py`.
