# Schroedinger's Agent

Bridging Known and Hypothetical States with Affordance‑Grounded LLMs

This project exposes a FastAPI service that can:

- Use MCP tools to ground answers in actions/data
- Run a multi-step agent with hierarchical planning (plan -> act -> observe)

Python 3.12+ are supported (as pinned in `pyproject.toml`). The LLM can be either Azure OpenAI or OpenAI.

## Quickstart

1. Install prerequisites

- Python 3.12
- [`uv`](https://github.com/astral-sh/uv) package manager (install via `brew install uv` or `pipx install uv`)

1. Install dependencies

```bash
# Create a virtual environment and install project deps from pyproject.toml/uv.lock
uv venv
source .venv/bin/activate
uv sync
```

1. Configure environment

Create a `.env` file in the repo root. Choose a provider and set the corresponding variables.

Required (all modes):

```bash
API_BEARER_TOKEN=devtoken123
LLM_PROVIDER=AZURE_OPENAI   # or OPENAI
LLM_MODEL=<deployment-or-model-name>
```

If LLM_PROVIDER=AZURE_OPENAI:

```bash
AZURE_ENDPOINT=https://YOUR_RESOURCE_NAME.openai.azure.com/
AZURE_API_KEY=<your-azure-openai-key>
AZURE_API_VERSION=2024-08-01-preview
```

If LLM_PROVIDER=OPENAI:

```bash
OPENAI_API_KEY=<your-openai-api-key>
```

The FastAPI app reads these values from `.env` at startup (see `dotenv.load_dotenv()` in `Agent/API/api.py`).

1. Start the MCP tools

```bash
bash tools.sh
# or
./tools.sh
```

This script starts the main MCP servers under `Tools/` (valuation analysis, financial health, news sentiment, report generation, etc.) in the background.

1. Start the API

```bash
bash start.sh
# or
uvicorn Agent.API.api:app --host 0.0.0.0 --port 8080 --reload
```

By default, the API persists agent traces and plans to a local ChromaDB database under the `DB/` directory. This directory is created automatically on first run.

1. Try the API (Bearer auth required)

Plain LLM (REST):

```bash
curl -sS -X POST http://localhost:8080/call \
  -H 'Authorization: Bearer devtoken123' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Hello"}' | jq
```

LLM + MCP (REST):

```bash
curl -sS -X POST http://localhost:8080/call_mcp \
  -H 'Authorization: Bearer devtoken123' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Run a valuation analysis and financial health check for ticker SNOW"}' | jq
```

Agent multi-step (REST):

```bash
curl -sS -X POST http://localhost:8080/agent \
  -H 'Authorization: Bearer devtoken123' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Produce an investment-style memo summarizing valuation, financial health, and recent news for ticker SNOW."}' | jq
```

WebSocket streaming (token via query param):

```bash
# LLM streaming
# ws://localhost:8080/ws/call?token=devtoken123

# LLM + MCP streaming
# ws://localhost:8080/ws/call_mcp?token=devtoken123

# Agent streaming (progress + final)
# ws://localhost:8080/ws/agent?token=devtoken123
```

## Optional: Streamlit Frontend

This repo includes a Streamlit app for visualizing agent plans and traces stored in ChromaDB.

With the virtual environment activated and the API having produced some runs (so `DB/` has data), start it with:

```bash
streamlit run frontend.py
```

The app expects the ChromaDB files in the local `DB/` directory by default.

## Configuration Reference

- LLM_PROVIDER: AZURE_OPENAI or OPENAI (required)
- LLM_MODEL: Azure deployment name (for AZURE_OPENAI) or model name (for OPENAI)
- API_BEARER_TOKEN: static token for REST and WS auth

Azure OpenAI (when LLM_PROVIDER=AZURE_OPENAI):

- AZURE_ENDPOINT: e.g. `https://YOUR_RESOURCE_NAME.openai.azure.com/`
- AZURE_API_KEY: your Azure OpenAI key
- AZURE_API_VERSION: e.g. 2024-08-01-preview

OpenAI (when LLM_PROVIDER=OPENAI):

- OPENAI_API_KEY: your OpenAI key

Put these in `.env` or export them in your shell before starting the API.

Other tools under `Tools/` may require additional API keys (for example, some financial MCP servers read tokens like `FINANCIAL_MODELING_PREP_TOKEN` from your environment). Check the individual tool Python files for their specific requirements.

## API Overview

All protected endpoints require either:

- REST: `Authorization: Bearer <API_BEARER_TOKEN>` header
- WebSocket: `?token=<API_BEARER_TOKEN>` query parameter

Endpoints:

- POST `/call` -> One-shot LLM call
  - Body: `{ "prompt": "..." }`
  - Returns: `{ result: string, trace: null, plan: null }`

- POST `/call_mcp` -> LLM call with MCP-enabled processing
  - Body: `{ "prompt": "..." }`
  - Returns: `{ result: string, trace: object }` (503 if MCP not ready)

- POST `/agent` -> Multi-step agent run
  - Body: `{ "prompt": "..." }`
  - Returns: `{ result: string, trace: array, plan: object|null }`

- WS `/ws/call` -> Streaming tokens from LLM
- WS `/ws/call_mcp` -> Streaming tokens + MCP traces
- WS `/ws/agent` -> Progress events and final payload

Auxiliary:

- GET `/tools` -> List discovered MCP tools (name, description, schema)
- GET `/health` -> `{ status, mcp_ready }`
- GET `/mcp/oauth/callback` -> OAuth callback sink used by some MCP integrations

## Agent Behavior

The agent runs a ReAct-style loop with hierarchical planning by default:

- Planning: decomposes the user goal into a tree of executable steps
- Acting: invokes MCP tools (e.g., the sample `sum` tool) with generated arguments
- Observing: summarizes outcomes to guide the next step

Key implementation files:

- `Agent/Domain/agent_service.py` — control loop and planning modes
- `Agent/Domain/agent_lifecycle.py` — session state transitions
- `Agent/Domain/planning/llm_planner.py` — LLM prompt orchestration for planning
- `Agent/Domain/prompts/*` — prompt templates and registry

Responses from `/agent` include:

- `result`: final observation rendered to Markdown
- `trace`: per-step trace of plan, act, observe
- `plan`: hierarchical plan summary of the current run (when available)

## MCP Tools

The main MCP servers live under `Tools/` and are started via:

```bash
bash tools.sh
```

This script launches several FastMCP servers (valuation analysis, financial health, news sentiment, report generation, etc.), which the API discovers at startup and exposes via `/tools`.

To modify or add tools, edit the corresponding files under `Tools/` and decorate functions with `@mcp.tool()`, then restart the tools script.

## Project Structure

- `Agent/API/api.py` — FastAPI app (REST + WebSockets), MCP startup, auth
- `Agent/Adapters/Outbound/*` — LLM adapters (Azure OpenAI / OpenAI), MCP client
- `Agent/Domain/*` — agent lifecycle, planning, prompts, utilities
- `Agent/Ports/Outbound/llm_interface.py` — LLM interface for adapters
- `start.sh` — convenience launcher for the API

Additional utilities:

- `frontend.py` — Streamlit UI to inspect stored plans/traces from ChromaDB (`DB/`)
- `Tools/*.py` — MCP servers and related utilities used by the agent; they can be run individually with `python Tools/<name>.py` or together via `tools.sh` (some require extra API keys as noted above)

## Troubleshooting

- 401 Unauthorized: Missing/incorrect `Authorization: Bearer` header (REST) or `?token=` query (WS)
- 503 MCP services not available: Start the MCP server first (`python Tools/test_server.py`) and restart the API
- ValueError: `LLM_PROVIDER` missing: Set `LLM_PROVIDER` to `OPENAI` or `AZURE_OPENAI` in `.env`
- Timeouts (500): Requests to MCP or the LLM exceeded the configured timeout; try again or simplify prompts

## Notes

- Python: `.python-version` pins 3.12; use that for local dev
- The API connects to MCP during app startup and keeps a background task for readiness
- Adjust ports as needed: API `8080`, MCP `8081`
