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

A from-scratch local MCP server with tools for weather, SQLite reads, local file operations, document summarization, contract-language risk review, and scanned PDF OCR:
- `weather(city)` → current weather via wttr.in
- `query_db(sql)` → read-only SQLite SELECT query
- `make_directory(path)` → create directories inside `MCP_FILE_OPS_ROOT`
- `move_file(source_path, destination_path)` → move files inside `MCP_FILE_OPS_ROOT`
- `move_files_by_glob(source_dir, pattern, destination_dir)` → move many files in one call (e.g., `*.txt`)
- `list_files(path=".", include_metadata=False)` → list files; optionally include file size + modified time
- `list_directories(path=".", include_metadata=False)` → list directories; optionally include modified time
- `list_directory_contents(path=".", include_metadata=False)` → list files + folders together; can include per-item metadata
- `read_file(path)` → read text files inside `MCP_FILE_OPS_ROOT`
- `inspect_file(path, preview_chars=4000, include_base64=False)` → metadata + preview for text/csv/image files
- `analyze_image_with_openai(path, prompt, model='gpt-4.1-mini')` → send image to OpenAI vision-capable model
- `summarize_documents_in_folder(folder_path, prompt=None, max_files=50, model='gpt-4.1-mini')` → summarize supported docs (`.txt`, `.md`, `.pdf`, `.docx`) in a folder
- `summarize_document(path, prompt=None, model='gpt-4.1-mini', max_extraction_attempts=3, output_txt_path=None, overwrite_output=False)` → summarize one document with extraction fallbacks
- `review_contract_language(path, focus=None, model='gpt-4.1-mini')` → flag potentially ambiguous/risky contract language
- `extract_text_from_scanned_pdf(path, max_pages=20, model='gpt-4.1-mini')` → OCR scanned PDFs with vision
- `write_text_file(path, content, overwrite=False)` → safe `.txt` writes under `MCP_FILE_OPS_ROOT`
- `create_spreadsheet(path, headers=None, overwrite=False, delimiter='comma')` → create a new `.csv`/`.tsv`/`.xlsx` spreadsheet under `MCP_FILE_OPS_ROOT`
- `edit_spreadsheet_cell(path, row_index, column, value, has_header=True, create_if_missing=False)` → create/edit one cell in `.csv`/`.tsv`/`.xlsx` spreadsheets under `MCP_FILE_OPS_ROOT`
- `list_google_calendar_events(calendar_id='primary', time_min=None, time_max=None, max_results=20)` → read existing Google Calendar events (always resolved to Eastern Time and a required time window)
- `create_google_calendar_event(summary, start_iso, end_iso, ...)` → create a new Google Calendar event

## Notes

- Default local MCP endpoint is: `http://127.0.0.1:8000/mcp`
- The server creates `demo.db` automatically with sample rows.
- `npx` requires Node.js/npm installed locally.
- `streamlit` is included in `requirements.txt`.
- OCR support uses `pypdfium2` to render PDF pages as images for vision-based extraction.
- Tool/server logging: `review_contract_language` writes JSONL lifecycle logs to `mcp_tool_events.jsonl` (or `MCP_TOOL_LOG_PATH`).
- Client logging: `client_openai_api.py` writes request/response/tool-output events to `mcp_client_events.jsonl` (or `MCP_CLIENT_LOG_PATH`).

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

## Google Calendar setup (read + create)

Use the steps below to enable Google Calendar read/create tools.

### Step 1: Enable API + create OAuth client
1. In Google Cloud Console, enable **Google Calendar API** and create an **OAuth client ID** for a desktop app.

### Step 2: Download credentials JSON
2. Download the client credentials JSON (often named `client_secret_....apps.googleusercontent.com.json`) and place it in the repo root.

### Step 3: Configure `.env`
3. In `.env`, set:
   - `GOOGLE_CALENDAR_CREDENTIALS_PATH=./client_secret_....apps.googleusercontent.com.json`
   - `GOOGLE_CALENDAR_TOKEN_PATH=./google_token.json`

### Step 4: Complete first-time OAuth consent
4. The first tool run opens Google OAuth consent in your browser and creates `google_token.json`.

### Step 5: Start server + use calendar tools
5. Start the MCP server and invoke either calendar tool.

### Environment variables
- `GOOGLE_CALENDAR_CREDENTIALS_PATH` (default `google_credentials.json`)
- `GOOGLE_CALENDAR_TOKEN_PATH` (default `google_token.json`)

If `GOOGLE_CALENDAR_CREDENTIALS_PATH` is omitted, the server tries:
1) `./google_credentials.json`
2) first matching `./client_secret*.json`

Both tools currently require the `https://www.googleapis.com/auth/calendar.events` scope (read/create events). Update/delete helpers are included in `server.py` as commented examples for future use.

### Calendar window + timezone behavior
- Eastern Time (`America/New_York`) is always used for calendar event queries.
- A time window is always required/resolved for `list_google_calendar_events`.
- If either `time_min` or `time_max` is missing, the server defaults to:
  - `time_min`: current timestamp in ET
  - `time_max`: end of current week in ET (Sunday `23:59:59.999`)
- Tool output always includes:
  - `resolved_time_min`
  - `resolved_time_max`
  - `resolved_timezone`

Example request (no explicit window):
```json
{
  "calendar_id": "primary",
  "max_results": 20
}
```

Example response (shape):
```json
{
  "calendar_id": "primary",
  "resolved_time_min": "2026-05-12T11:32:44.123456-04:00",
  "resolved_time_max": "2026-05-17T23:59:59.999000-04:00",
  "resolved_timezone": "America/New_York",
  "count": 2,
  "events": []
}
```

## New document + contract tools

### Supported document types
- Digital text: `.txt`, `.md`, `.pdf` (digitally readable text), `.docx`
- Scanned/image PDFs: use `extract_text_from_scanned_pdf`

### `summarize_documents_in_folder(folder_path: str, prompt: str | None = None, max_files: int = 50, model: str = "gpt-4.1-mini")`
- Safely resolves folder under `MCP_FILE_OPS_ROOT`.
- Reads up to `max_files` files in that folder (non-recursive).
- Skips unsupported or unreadable files and reports them in `skipped_files`.
- Returns JSON with:
  - per-file summaries
  - overall summary
  - processing metadata

### `summarize_document(path: str, prompt: str | None = None, model: str = "gpt-4.1-mini", max_extraction_attempts: int = 3, output_txt_path: str | None = None, overwrite_output: bool = False)`
- Safely resolves file under `MCP_FILE_OPS_ROOT`.
- Uses classify → plan → extract behavior.
- Applies fallback extraction (e.g., digital PDF first, then OCR), bounded by `max_extraction_attempts`.
- Can optionally write the summary to `output_txt_path` (must be `.txt`).

Example payload:
```json
{
  "folder_path": "contracts/q1",
  "prompt": "Focus on key obligations and risks",
  "max_files": 25
}
```

### `review_contract_language(path: str, focus: str | None = None, model: str = "gpt-4.1-mini")`
- Accepts `.txt`, `.md`, `.pdf`, `.docx`.
- Extracts text and asks OpenAI to return structured JSON findings:
  - `potential_issues[]` with `risk_type`, `severity`, `why_flagged`, `suggested_plain_language_revision`, etc.
- Adds explicit disclaimer: **not legal advice**.

Example payload:
```json
{
  "path": "contracts/vendor_agreement.docx",
  "focus": "Look for hidden fee signals and one-sided termination language"
}
```

### `extract_text_from_scanned_pdf(path: str, max_pages: int = 20, model: str = "gpt-4.1-mini")`
- Intended for scanned/image PDFs.
- Renders pages to images using `pypdfium2`, then sends each page to a vision-capable OpenAI model.
- Returns combined extracted text and per-page extraction metadata.
- Defensively limits processing with `max_pages`.

Example payload:
```json
{
  "path": "scans/contract_scan.pdf",
  "max_pages": 10
}
```

### `write_text_file(path: str, content: str, overwrite: bool = false)`
- Only writes `.txt`.
- Enforces path safety under `MCP_FILE_OPS_ROOT`.
- Creates parent directories when needed.
- Returns `path` + `bytes_written` metadata.

Example payload:
```json
{
  "path": "notes/summary.txt",
  "content": "Key findings...",
  "overwrite": false
}
```

### `create_spreadsheet(path: str, headers: list[str] | None = None, overwrite: bool = false, delimiter: str = "comma")`
- Creates a new spreadsheet under `MCP_FILE_OPS_ROOT`.
- Supports `.csv`, `.tsv`, and `.xlsx` extensions.
- Optional `headers` writes a first-row header.
- For text files, `delimiter` accepts `comma` or `tab` (extension still controls output type for `.csv`/`.tsv`).

Example payload:
```json
{
  "path": "spreadsheets/new_leads.csv",
  "headers": ["name", "email", "status"],
  "overwrite": false
}
```

### `edit_spreadsheet_cell(path: str, row_index: int, column: str | int, value: str, has_header: bool = true, create_if_missing: bool = false)`
- Supports `.csv`, `.tsv`, and `.xlsx` files under `MCP_FILE_OPS_ROOT`.
- Updates exactly one cell and writes the sheet back to disk.
- Can create a new spreadsheet when `create_if_missing=true`.
- `row_index` is 0-based over data rows when `has_header=true`; otherwise 0-based over all rows.
- `column` can be a header name (string) or 0-based column index (int).
- If a header-name column does not exist, it is added automatically.

Example payload:
```json
{
  "path": "spreadsheets/leads.xlsx",
  "row_index": 2,
  "column": "status",
  "value": "contacted",
  "has_header": true,
  "create_if_missing": true
}
```
