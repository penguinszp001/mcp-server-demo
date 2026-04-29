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

```bash
mcp-server-demo
```

This starts the local server and creates `demo.db` automatically with sample rows.

## 3) Quick manual MCP check (optional)

If you have MCP Inspector installed:

```bash
npx @modelcontextprotocol/inspector
```

Then connect to your local Python server.

## 4) OpenAI API integration option

1. Copy env file and fill key:

```bash
cp .env.example .env
```

2. Start the server in one terminal.

3. In a second terminal, run:

```bash
python client_openai_api.py
```

> Note: this uses OpenAI Responses API with an MCP tool definition pointing at `http://localhost:8000/mcp`.

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
