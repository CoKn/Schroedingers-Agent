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

2. Install dependencies
```bash
# Create a virtual environment and install project deps from pyproject.toml/uv.lock
uv venv
source .venv/bin/activate
uv sync
```

3. Configure environment

Create a `.env` file in the repo root with the following variables:
```dotenv
# API Authentication
API_BEARER_TOKEN=

# LLM Configuration
LLM_PROVIDER=OPENAI
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=
OPENAI_API_KEY_TWO=

# Financial Data APIs
ALPHAVANTAGE_API_KEY=
FINANCIAL_MODELING_PREP_TOKEN=
SEC_USER_AGENT=
SEC_API_KEY=

# Gmail Integration (optional)
GMAIL_ADDRESS=
GMAIL_PASSWORD=
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
```

**Note:** If using Azure OpenAI instead, replace the OpenAI variables with:
```dotenv
LLM_PROVIDER=AZURE_OPENAI
LLM_MODEL=<deployment-name>
AZURE_ENDPOINT=https://YOUR_RESOURCE_NAME.openai.azure.com/
AZURE_API_KEY=<your-azure-openai-key>
AZURE_API_VERSION=2024-08-01-preview
```

4. Configure Gmail Integration (Optional)

If you plan to use Gmail-related MCP tools, you need to set up Google API credentials:

a. Create a Google Cloud project and enable the Gmail API
b. Create OAuth 2.0 credentials (Desktop application type)
c. Download the credentials and save as `credentials.json` in the project root:
```json
{
  "installed": {
    "client_id": "<your-client-id>",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "<your-client-secret>",
    "redirect_uris": ["http://localhost"]
  }
}
```

d. On first run, you'll be prompted to authorize the application. This will create a `token.json` file:
```json
{
  "token": "<access-token>",
  "refresh_token": "<refresh-token>",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "<your-client-id>",
  "client_secret": "<your-client-secret>",
  "scopes": ["https://www.googleapis.com/auth/gmail.send"],
  "universe_domain": "googleapis.com",
  "account": "<your-email>",
  "expiry": "<expiry-timestamp>"
}
```

5. Start the MCP tools
```bash
bash tools.sh
# or
./tools.sh
```

This script starts the main MCP servers under `Tools/` (valuation analysis, financial health, news sentiment, report generation, etc.) in the background.

6. Start the API
```bash
bash start.sh
# or
uvicorn Agent.API.api:app --host 0.0.0.0 --port 8080 --reload
```

By default, the API persists agent traces and plans to a local ChromaDB database under the `DB/` directory. This directory is created automatically on first run.

7. Try the API (Bearer auth required)

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

### Required Variables

- **API_BEARER_TOKEN**: Static token for REST and WebSocket authentication
- **LLM_PROVIDER**: `OPENAI` or `AZURE_OPENAI`
- **LLM_MODEL**: Model name (OpenAI) or deployment name (Azure)

### LLM Provider Configuration

**OpenAI:**
- **OPENAI_API_KEY**: Your OpenAI API key
- **OPENAI_API_KEY_TWO**: Secondary API key (for fallback/load balancing)

**Azure OpenAI:**
- **AZURE_ENDPOINT**: e.g. `https://YOUR_RESOURCE_NAME.openai.azure.com/`
- **AZURE_API_KEY**: Your Azure OpenAI key
- **AZURE_API_VERSION**: e.g. `2024-08-01-preview`

### Financial Data APIs

- **ALPHAVANTAGE_API_KEY**: Alpha Vantage API key for market data
- **FINANCIAL_MODELING_PREP_TOKEN**: Financial Modeling Prep API token
- **SEC_USER_AGENT**: User agent string for SEC EDGAR API (format: `Name email@example.com`)
- **SEC_API_KEY**: SEC API key (if required by your tools)

### Gmail Integration (Optional)

- **GMAIL_ADDRESS**: Gmail account email
- **GMAIL_PASSWORD**: Gmail account password or app-specific password
- **GMAIL_CLIENT_ID**: OAuth 2.0 client ID from Google Cloud Console
- **GMAIL_CLIENT_SECRET**: OAuth 2.0 client secret from Google Cloud Console

Additionally, you need `credentials.json` and `token.json` files (see step 4 above).

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

- **401 Unauthorized**: Missing/incorrect `Authorization: Bearer` header (REST) or `?token=` query (WS)
- **503 MCP services not available**: Start the MCP server first (`bash tools.sh`) and restart the API
- **ValueError: `LLM_PROVIDER` missing**: Set `LLM_PROVIDER` to `OPENAI` or `AZURE_OPENAI` in `.env`
- **Missing API keys**: Ensure all required keys in `.env` are populated (check error messages for specific missing keys)
- **Gmail authentication errors**: Verify `credentials.json` is present and properly formatted; delete `token.json` and re-authenticate if needed
- **Timeouts (500)**: Requests to MCP or the LLM exceeded the configured timeout; try again or simplify prompts

## Notes

- Python: `.python-version` pins 3.12; use that for local dev
- The API connects to MCP during app startup and keeps a background task for readiness
- Adjust ports as needed: API `8080`, MCP tools typically run on ports `8081+`
