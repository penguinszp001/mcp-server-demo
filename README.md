# MCP Server Demo (Python)

A from-scratch local MCP server with two tools:
- `weather(city)` → current weather via wttr.in
- `query_db(sql)` → read-only SQLite SELECT query

## 1) Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## 2) Run the MCP server

### Option A: stdio mode (default)

```bash
mcp-server-demo
```

This mode is best for local tool-host integrations that launch your server process directly.

### Option B: HTTP mode (for manual testing via `curl`)

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=8000 MCP_PATH=/mcp mcp-server-demo
```

You should immediately see startup logs, then a periodic health heartbeat every 30 seconds by default.
Set `MCP_HEARTBEAT_SECONDS=0` to disable heartbeats.

This starts an HTTP MCP endpoint at:

`http://127.0.0.1:8000/mcp`

The server also creates `demo.db` automatically with sample rows.

## 3) Manual checks

### A) Basic endpoint reachability (transport/session behavior)

```bash
curl -i -H "Accept: text/event-stream" http://127.0.0.1:8000/mcp
```

`streamable-http` requires an SSE-capable `Accept` header on `GET`, **and** the server expects
an MCP session id for ongoing calls. A plain `GET` can return `400 Bad Request` with
`"Missing session ID"`; this is normal for session-based transports and means the server is up.

### B) Protocol-level test (recommended)

Use MCP Inspector to verify tools and invoke them:

```bash
npx @modelcontextprotocol/inspector
```

Connect to your local Python server and confirm `weather` and `query_db` are listed.

### C) If using OpenAI-hosted Responses API

If you run `python client_openai_api.py` against `http://127.0.0.1:8000/mcp`, OpenAI-hosted
infrastructure cannot reach your machine's loopback interface. In that case you should expose
the local server with a tunnel and point `MCP_SERVER_URL` to that public URL.

Example:

```bash
# terminal 1
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 MCP_PATH=/mcp mcp-server-demo

# terminal 2 (example tunnel command; choose your preferred provider)
ngrok http 8000

# terminal 3
MCP_SERVER_URL=https://<your-public-url>/mcp python client_openai_api.py
```

## 4) OpenAI API integration option

1. Copy env file and fill key:

```bash
cp .env.example .env
```

2. Start the server in HTTP mode:

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=8000 MCP_PATH=/mcp mcp-server-demo
```

3. In a second terminal, run:

```bash
python client_openai_api.py
```

4. Launch the web chat UI (optional):

```bash
streamlit run web_client.py
```

This interface keeps chat history in the browser session, so each new question includes prior turns for conversation context.

> Note: the client uses OpenAI Responses API with an MCP tool definition pointing at `MCP_SERVER_URL`
> (default: `http://127.0.0.1:8000/mcp`). You can override this for custom host/port/path.

If you get an MCP tool-list retrieval error from OpenAI:
- Ensure your server is running in **streamable-http** mode (not stdio mode).
- Ensure host/port/path match exactly in both terminals.
- Prefer `127.0.0.1` over `localhost` to avoid loopback resolution mismatches.
- If your call is made by OpenAI's hosted API, `127.0.0.1` is not reachable from OpenAI.
  Use a publicly reachable URL (for example, via a tunnel) and set `MCP_SERVER_URL`.

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
- `pyproject.toml` — dependencies + script entrypoint.
