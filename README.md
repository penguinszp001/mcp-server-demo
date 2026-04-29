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
Fill in your OPENAI_API_KEY and keep MCP_DEMO_DB_PATH=demo.db.
If you want to use file tools, set MCP_FILE_OPS_ROOT to a local folder path that the server is allowed to manage.

You will fill out the MCP_SERVER_URL in a later step

4) If you plan to expose your local MCP server publicly, make sure ngrok is installed `sudo snap install ngrok` and your account is set up and authenticated first. You can set up an account for free.
Once set up, add token using terminal `ngrok config add-authtoken <AUTHTOKEN>` You can find the token on `https://dashboard.ngrok.com/get-started/your-authtoken`
5) Start the MCP server (HTTP transport).

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 MCP_PATH=/mcp mcp-server-demo
```

6) In a new terminal, start ngrok.

```bash
ngrok http 8000
```
Once you have ngrok running, you need to update MCP_SERVER_URL in your .env file
use the address from 'Forwarding'. Your .env will now look like `MCP_SERVER_URL=<Full forwarding Address>/mcp`

7) (Optional) In another terminal, run MCP Inspector.

```bash
npx @modelcontextprotocol/inspector
```
It should open up a web browser. In the left hand panel update Command to be `mcp-server-demo`
Press connect. You can select "tools" in the top menu to test the available tools and see history and notifications at the bottom of the page

8) (Optional) Launch the Streamlit client.

```bash
streamlit run web_client.py
```

---

A from-scratch local MCP server with tools for weather, SQLite reads, and local file operations:
- `weather(city)` → current weather via wttr.in
- `query_db(sql)` → read-only SQLite SELECT query
- `make_directory(path)` → create directories inside `MCP_FILE_OPS_ROOT`
- `move_file(source_path, destination_path)` → move files inside `MCP_FILE_OPS_ROOT`
- `move_files_by_glob(source_dir, pattern, destination_dir)` → move many files in one call (e.g., `*.txt`)
- `list_files(path=".")` → list files in a folder inside `MCP_FILE_OPS_ROOT`
- `list_directories(path=".")` → list directories in a folder inside `MCP_FILE_OPS_ROOT`
- `read_file(path)` → read text files inside `MCP_FILE_OPS_ROOT`
- `inspect_file(path, preview_chars=4000, include_base64=False)` → metadata + preview for text/csv/image files
- `analyze_image_with_openai(path, prompt, model='gpt-4.1-mini')` → send image to OpenAI vision-capable model

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

### File operation tools
- All file operations are constrained to `MCP_FILE_OPS_ROOT`.
- The server rejects paths that try to escape that root.
- `MCP_FILE_OPS_ROOT` directories are created automatically if they do not exist.
