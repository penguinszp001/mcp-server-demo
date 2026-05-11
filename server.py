from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import base64
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from docx import Document
from pypdf import PdfReader
from pypdfium2 import PdfDocument

load_dotenv()

DB_PATH = Path(os.getenv("MCP_DEMO_DB_PATH", "demo.db"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
MCP_PATH = os.getenv("MCP_PATH", "/mcp")
HEARTBEAT_SECONDS = int(os.getenv("MCP_HEARTBEAT_SECONDS", "30"))
FILE_OPS_ROOT = os.getenv("MCP_FILE_OPS_ROOT")

mcp = FastMCP(
    "local-mcp-demo",
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path=MCP_PATH,
)


def _db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _bootstrap_db() -> None:
    with _db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) AS c FROM notes").fetchone()["c"]
        if count == 0:
            conn.executemany(
                "INSERT INTO notes(title, body) VALUES(?, ?)",
                [
                    ("Welcome", "Your local MCP SQLite tool is working."),
                    ("Next Step", "Try running SELECT * FROM notes;"),
                ],
            )


def _resolve_file_ops_path(path: str | None = None) -> Path:
    if not FILE_OPS_ROOT:
        raise ValueError("MCP_FILE_OPS_ROOT is not configured in .env.")

    root = Path(FILE_OPS_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    target = root if path is None else (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the configured MCP_FILE_OPS_ROOT.")
    return target


SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def _extract_text_from_digital_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


def _extract_text_from_docx(path: Path) -> str:
    document = Document(str(path))
    paragraphs = [p.text for p in document.paragraphs if p.text]
    return "\n".join(paragraphs).strip()


def extract_text_from_file(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    if extension == ".pdf":
        return _extract_text_from_digital_pdf(path)
    if extension == ".docx":
        return _extract_text_from_docx(path)
    raise ValueError(f"Unsupported file type: {extension}")


def _summarize_text_with_openai(text: str, prompt: str | None = None, model: str = "gpt-4.1-mini") -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    guidance = prompt or "Summarize the main points, key obligations, and notable risks."
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": "You are a concise document summarization assistant.",
            },
            {
                "role": "user",
                "content": (
                    f"Guidance: {guidance}\n\n"
                    "Document text:\n"
                    f"{text[:200000]}"
                ),
            },
        ],
    )
    return response.output_text


@mcp.tool()
def weather(city: str) -> str:
    """Return current weather for a city using wttr.in."""
    response = httpx.get(f"https://wttr.in/{city}", params={"format": "j1"}, timeout=20)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    current = data["current_condition"][0]

    summary = {
        "city": city,
        "temp_c": current.get("temp_C"),
        "temp_f": current.get("temp_F"),
        "feels_like_c": current.get("FeelsLikeC"),
        "description": current.get("weatherDesc", [{}])[0].get("value"),
        "humidity": current.get("humidity"),
        "wind_kmph": current.get("windspeedKmph"),
    }
    return json.dumps(summary, indent=2)


@mcp.tool()
def query_db(sql: str) -> str:
    """Run a read-only SELECT query against local SQLite demo.db."""
    normalized = sql.strip().lower().rstrip(";")
    if not normalized.startswith("select"):
        raise ValueError("Only SELECT queries are allowed for this demo.")

    with _db_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return json.dumps([dict(r) for r in rows], indent=2)


@mcp.tool()
def make_directory(path: str) -> str:
    """Create a directory inside MCP_FILE_OPS_ROOT."""
    target = _resolve_file_ops_path(path)
    target.mkdir(parents=True, exist_ok=True)
    return f"Created directory: {target}"


@mcp.tool()
def move_file(source_path: str, destination_path: str) -> str:
    """Move a file from source_path to destination_path inside MCP_FILE_OPS_ROOT."""
    source = _resolve_file_ops_path(source_path)
    destination = _resolve_file_ops_path(destination_path)

    if not source.is_file():
        raise ValueError(f"Source file does not exist: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return f"Moved file from {source} to {destination}"


@mcp.tool()
def move_files_by_glob(source_dir: str, pattern: str, destination_dir: str) -> str:
    """Move all files matching a glob pattern from source_dir into destination_dir."""
    source_root = _resolve_file_ops_path(source_dir)
    destination_root = _resolve_file_ops_path(destination_dir)

    if not source_root.is_dir():
        raise ValueError(f"Source directory does not exist: {source_root}")

    destination_root.mkdir(parents=True, exist_ok=True)

    moved: list[str] = []
    skipped: list[str] = []
    for source in sorted(source_root.glob(pattern)):
        if not source.is_file():
            continue

        destination = destination_root / source.name
        if destination.exists():
            skipped.append(source.name)
            continue

        shutil.move(str(source), str(destination))
        moved.append(source.name)

    summary = {
        "source_dir": str(source_root),
        "destination_dir": str(destination_root),
        "pattern": pattern,
        "moved_count": len(moved),
        "skipped_existing_count": len(skipped),
        "moved_files": moved,
        "skipped_existing_files": skipped,
    }
    return json.dumps(summary, indent=2)


@mcp.tool()
def list_files(path: str = ".") -> str:
    """List files directly inside a folder within MCP_FILE_OPS_ROOT."""
    target = _resolve_file_ops_path(path)
    if not target.is_dir():
        raise ValueError(f"Not a directory: {target}")

    files = sorted(p.name for p in target.iterdir() if p.is_file())
    return json.dumps(files, indent=2)


@mcp.tool()
def list_directories(path: str = ".") -> str:
    """List directories directly inside a folder within MCP_FILE_OPS_ROOT."""
    target = _resolve_file_ops_path(path)
    if not target.is_dir():
        raise ValueError(f"Not a directory: {target}")

    directories = sorted(p.name for p in target.iterdir() if p.is_dir())
    return json.dumps(directories, indent=2)


@mcp.tool()
def read_file(path: str) -> str:
    """Read a UTF-8 text file inside MCP_FILE_OPS_ROOT."""
    target = _resolve_file_ops_path(path)
    if not target.is_file():
        raise ValueError(f"File does not exist: {target}")
    return target.read_text(encoding="utf-8")


@mcp.tool()
def inspect_file(path: str, preview_chars: int = 4000, include_base64: bool = False) -> str:
    """Return file metadata and content preview for text/csv/image workflows."""
    target = _resolve_file_ops_path(path)
    if not target.is_file():
        raise ValueError(f"File does not exist: {target}")

    mime_type, _ = mimetypes.guess_type(str(target))
    if not mime_type:
        mime_type = "application/octet-stream"

    raw = target.read_bytes()
    result: dict[str, Any] = {
        "path": str(target),
        "name": target.name,
        "size_bytes": len(raw),
        "mime_type": mime_type,
    }

    if mime_type.startswith("text/") or mime_type in {"application/json", "text/csv"}:
        text = raw.decode("utf-8", errors="replace")
        result["text_preview"] = text[:preview_chars]
        result["text_preview_truncated"] = len(text) > preview_chars
    elif mime_type.startswith("image/"):
        result["image_note"] = "Use analyze_image_with_openai for model vision interpretation."

    if include_base64:
        result["base64"] = base64.b64encode(raw).decode("ascii")

    return json.dumps(result, indent=2)


@mcp.tool()
def analyze_image_with_openai(path: str, prompt: str, model: str = "gpt-4.1-mini") -> str:
    """Analyze an image file with an OpenAI vision-capable model."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    target = _resolve_file_ops_path(path)
    if not target.is_file():
        raise ValueError(f"File does not exist: {target}")

    mime_type, _ = mimetypes.guess_type(str(target))
    if not mime_type or not mime_type.startswith("image/"):
        raise ValueError(f"File is not an image: {target}")

    image_bytes = target.read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{image_b64}"

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
    )
    return response.output_text


@mcp.tool()
def summarize_documents_in_folder(
    folder_path: str,
    prompt: str | None = None,
    max_files: int = 50,
    model: str = "gpt-4.1-mini",
) -> str:
    """Summarize supported documents in a folder and return per-file + overall summaries."""
    if max_files < 1:
        raise ValueError("max_files must be at least 1.")
    folder = _resolve_file_ops_path(folder_path)
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")

    files = [p for p in sorted(folder.iterdir()) if p.is_file()][:max_files]
    summaries: list[dict[str, Any]] = []
    skipped_files: list[dict[str, str]] = []

    for file_path in files:
        if file_path.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
            skipped_files.append({"path": str(file_path), "reason": "unsupported_file_type"})
            continue
        try:
            text = extract_text_from_file(file_path)
            if not text.strip():
                skipped_files.append({"path": str(file_path), "reason": "empty_or_unreadable_content"})
                continue
            summary = _summarize_text_with_openai(text=text, prompt=prompt, model=model)
            summaries.append(
                {
                    "path": str(file_path),
                    "file_name": file_path.name,
                    "summary": summary,
                    "char_count": len(text),
                }
            )
        except Exception as exc:
            skipped_files.append({"path": str(file_path), "reason": str(exc)})

    combined = "\n\n".join(
        f"{item['file_name']}:\n{item['summary']}" for item in summaries
    )[:200000]
    overall_summary = ""
    if combined:
        overall_summary = _summarize_text_with_openai(
            text=combined,
            prompt=prompt or "Create an overall summary across these file summaries.",
            model=model,
        )

    return json.dumps(
        {
            "folder_path": str(folder),
            "max_files": max_files,
            "processed_files": len(summaries),
            "skipped_files": skipped_files,
            "per_file_summaries": summaries,
            "overall_summary": overall_summary,
        },
        indent=2,
    )


@mcp.tool()
def review_contract_language(path: str, focus: str | None = None, model: str = "gpt-4.1-mini") -> str:
    """Flag potentially misleading or risky contract language (not legal advice)."""
    target = _resolve_file_ops_path(path)
    if not target.is_file():
        raise ValueError(f"File does not exist: {target}")
    if target.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
        raise ValueError("Supported file types: .txt, .md, .pdf, .docx")

    text = extract_text_from_file(target)
    if not text.strip():
        raise ValueError("No readable text extracted from file.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    guidance = focus or "Find ambiguous, one-sided, vague, or potentially misleading language."
    schema_prompt = (
        "Return strict JSON with keys: potential_issues (array), disclaimer. "
        "Each issue object must include: clause_excerpt, risk_type, severity, why_flagged, suggested_plain_language_revision."
    )
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": "You are a contract risk reviewer. This is not legal advice."},
            {"role": "user", "content": f"{schema_prompt}\nFocus: {guidance}\n\nContract text:\n{text[:200000]}"},
        ],
    )
    output_text = response.output_text
    payload = json.loads(output_text)
    payload["document_path"] = str(target)
    payload["disclaimer"] = "This review is automated and is not legal advice."
    return json.dumps(payload, indent=2)


@mcp.tool()
def extract_text_from_scanned_pdf(path: str, max_pages: int = 20, model: str = "gpt-4.1-mini") -> str:
    """Extract text from scanned/image PDFs by rendering pages and using vision."""
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1.")
    target = _resolve_file_ops_path(path)
    if not target.is_file():
        raise ValueError(f"File does not exist: {target}")
    if target.suffix.lower() != ".pdf":
        raise ValueError("This OCR tool only accepts .pdf files.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")
    client = OpenAI(api_key=api_key)

    pdf = PdfDocument(str(target))
    page_count = len(pdf)
    pages_to_process = min(page_count, max_pages)
    extracted_pages: list[dict[str, Any]] = []
    combined_parts: list[str] = []

    for index in range(pages_to_process):
        page = pdf[index]
        image = page.render(scale=2).to_pil()
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        page_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        data_url = f"data:image/png;base64,{page_b64}"
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Extract all readable text from this scanned page."},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        page_text = response.output_text.strip()
        extracted_pages.append({"page_number": index + 1, "chars_extracted": len(page_text)})
        combined_parts.append(f"[Page {index + 1}]\n{page_text}")

    return json.dumps(
        {
            "path": str(target),
            "total_pages": page_count,
            "processed_pages": pages_to_process,
            "truncated": page_count > max_pages,
            "pages": extracted_pages,
            "text": "\n\n".join(combined_parts),
        },
        indent=2,
    )


@mcp.tool()
def write_text_file(path: str, content: str, overwrite: bool = False) -> str:
    """Write a .txt file under MCP_FILE_OPS_ROOT."""
    target = _resolve_file_ops_path(path)
    if target.suffix.lower() != ".txt":
        raise ValueError("Only .txt files can be written by this tool.")
    if target.exists() and not overwrite:
        raise ValueError(f"File already exists and overwrite is false: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    target.write_bytes(encoded)
    return json.dumps(
        {"path": str(target), "bytes_written": len(encoded), "overwrite": overwrite},
        indent=2,
    )


def main() -> None:
    _bootstrap_db()

    transport = MCP_TRANSPORT
    print(f"[mcp-server-demo] Bootstrapped database at: {DB_PATH.resolve()}", flush=True)

    if transport == "streamable-http":
        print(
            f"[mcp-server-demo] Starting streamable-http MCP server at "
            f"http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}",
            flush=True,
        )

        if HEARTBEAT_SECONDS > 0:
            def _heartbeat() -> None:
                while True:
                    print(
                        f"[mcp-server-demo] healthy: transport=streamable-http "
                        f"url=http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}",
                        flush=True,
                    )
                    time.sleep(HEARTBEAT_SECONDS)

            threading.Thread(target=_heartbeat, daemon=True).start()

        mcp.run(transport="streamable-http")
        return

    print("[mcp-server-demo] Starting stdio MCP server.", flush=True)
    print("[mcp-server-demo] Note: OpenAI HTTP client example requires streamable-http mode.", flush=True)

    mcp.run()


if __name__ == "__main__":
    main()
