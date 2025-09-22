# Schroedinger's Agent

Bridging Known and Hypothetical States with Affordance‑Grounded LLMs

## Run The Project

- Prerequisites: macOS, Python 3.12+, and an Azure OpenAI deployment.

1. Install dependencies

```bash
# Create a virtual environment and install project deps from pyproject.toml/uv.lock
uv venv
source .venv/bin/activate
uv sync
```

2. Set environment variables

Create a `.env` file in the repo root with:

```bash
API_BEARER_TOKEN=devtoken123
AZURE_ENDPOINT=https://<your-resource-name>.openai.azure.com/
AZURE_API_KEY=<your-azure-openai-key>
AZURE_API_VERSION=2024-08-01-preview
LLM_MODEL=<your-deployment-name>
```

3. Start the MCP tools server

```bash
python Tools/server.py
```

This exposes MCP tools over streamable HTTP on `http://0.0.0.0:8081`.

4. Start the API

```bash
bash start.sh
# or
uvicorn Agent.API.api:app --host 0.0.0.0 --port 8080 --reload
```

5. Call the API (Bearer auth required)

HTTP JSON call to plain LLM:

```bash
curl -sS -X POST http://localhost:8080/call \
  -H 'Authorization: Bearer devtoken123' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Hello"}' | jq
```

Use MCP-enabled processing:

```bash
curl -sS -X POST http://localhost:8080/call_mcp \
  -H 'Authorization: Bearer devtoken123' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Track order O-10006"}' | jq
```

Agent multi-step run:

```bash
curl -sS -X POST http://localhost:8080/agent \
  -H 'Authorization: Bearer devtoken123' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"I never got my product with the order id O-10006. I would like to reorder the product."}' | jq
```

Notes

- MCP startup happens during API app lifespan; ensure the tools server is running before calling MCP/agent endpoints.
- The default MCP tools server port is 8081; adjust if needed inside `Tools/server.py`.
