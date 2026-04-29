# MCP Server Demo (Python)

## Quickstart (local run)

1) Create and activate a virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate
```

2) Install Python dependencies.

```bash
pip install -U pip
pip install -r requirements.txt
pip install -e .
```

3) Set up environment variables.

```bash
cp .env.example .env
```

4) If you plan to expose your local MCP server publicly, make sure your ngrok account is set up and authenticated first.

5) Start the MCP server (HTTP transport).

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 MCP_PATH=/mcp mcp-server-demo
```

6) In a new terminal, start ngrok.

```bash
ngrok http 8000
```

7) (Optional) In another terminal, run MCP Inspector.

```bash
npx @modelcontextprotocol/inspector
```

8) (Optional) Launch the Streamlit client.

```bash
streamlit run web_client.py
```

---

A from-scratch local MCP server with two tools:
- `weather(city)` → current weather via wttr.in
- `query_db(sql)` → read-only SQLite SELECT query

## Notes

- Default local MCP endpoint is: `http://127.0.0.1:8000/mcp`
- The server creates `demo.db` automatically with sample rows.
- `npx` requires Node.js/npm installed locally.
- `streamlit` is included in `requirements.txt`.

## OpenAI API integration option

1. Ensure `.env` includes your key and MCP server URL.
2. Start server in HTTP mode.
3. Run:

```bash
python client_openai_api.py
```

## Tool behavior

### `weather(city: str)`
Returns JSON summary fields including temperature, feels-like, humidity, wind, and short conditions.

### `query_db(sql: str)`
- Allows **only** `SELECT ...` queries.
- Returns rows as JSON.
- Rejects non-SELECT SQL for safety in this starter demo.

## Project files

- `server.py` — FastMCP server + tool definitions.
- `client_openai_api.py` — simple OpenAI API call that can invoke MCP tools.
- `web_client.py` — Streamlit chat client.
- `pyproject.toml` — package metadata + script entrypoint.
- `requirements.txt` — pinned runtime dependencies for local setup.
