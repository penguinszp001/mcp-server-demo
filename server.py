from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import base64
import mimetypes
import traceback
from datetime import datetime, timezone
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


LOG_PATH = Path(os.getenv("MCP_TOOL_LOG_PATH", "mcp_tool_events.jsonl"))


def _write_tool_event(event: dict[str, Any]) -> None:
    event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    serialized = json.dumps(event, ensure_ascii=False)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(serialized + "\n")
    print(f"[mcp-tool-log] {serialized}", flush=True)


def _truncate_for_log(value: Any, max_chars: int = 2000) -> Any:
    try:
        as_text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        as_text = str(value)
    if len(as_text) <= max_chars:
        return value
    return f"{as_text[:max_chars]}...<truncated>"


def _run_tool_with_logging(tool_name: str, tool_args: dict[str, Any], fn: Any) -> str:
    start = time.time()
    _write_tool_event({"event": "tool_start", "tool": tool_name, "args": _truncate_for_log(tool_args)})
    try:
        result = fn()
        _write_tool_event(
            {
                "event": "tool_success",
                "tool": tool_name,
                "duration_ms": int((time.time() - start) * 1000),
                "result_preview": _truncate_for_log(result),
            }
        )
        return result
    except Exception as exc:
        _write_tool_event(
            {
                "event": "tool_error",
                "tool": tool_name,
                "duration_ms": int((time.time() - start) * 1000),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        raise




def _stage_log(stage: str, **fields: Any) -> None:
    payload = {"event": stage}
    payload.update(fields)
    _write_tool_event(payload)


def _printable_text_ratio(text: str) -> float:
    if not text:
        return 0.0
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\t\r")
    return printable / len(text)


def _quality_score(text: str) -> dict[str, Any]:
    char_count = len(text)
    whitespace_ratio = (sum(1 for ch in text if ch.isspace()) / char_count) if char_count else 1.0
    printable_ratio = _printable_text_ratio(text)
    quality_ok = char_count >= 80 and printable_ratio >= 0.85 and whitespace_ratio < 0.7
    return {
        "char_count": char_count,
        "printable_text_ratio": round(printable_ratio, 4),
        "whitespace_ratio": round(whitespace_ratio, 4),
        "quality_ok": quality_ok,
    }


def _classify_file(path: Path) -> dict[str, Any]:
    extension = path.suffix.lower()
    mime_type, _ = mimetypes.guess_type(str(path))
    capability = "unsupported"
    page_count = None
    has_embedded_text = None
    if extension in {".txt", ".md"}:
        capability = "direct_text"
    elif extension == ".docx":
        capability = "docx_parse"
    elif extension == ".pdf":
        capability = "pdf_unknown"
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        probe = "\n".join((reader.pages[i].extract_text() or "") for i in range(min(2, page_count)))
        has_embedded_text = bool(probe.strip())
        capability = "digitally_extractable_pdf" if has_embedded_text else "likely_scanned_pdf"

    profile = {
        "path": str(path),
        "name": path.name,
        "extension": extension,
        "mime_type": mime_type or "application/octet-stream",
        "size_bytes": path.stat().st_size,
        "page_count": page_count,
        "has_embedded_text": has_embedded_text,
        "capability_profile": capability,
    }
    _stage_log("classify_file", profile=profile)
    return profile


def _build_extraction_plan(profile: dict[str, Any]) -> dict[str, Any]:
    ext = profile["extension"]
    if ext in {".txt", ".md"}:
        methods = ["direct_text_read"]
    elif ext == ".docx":
        methods = ["docx_parse"]
    elif ext == ".pdf":
        methods = ["digital_pdf_parse", "ocr_pdf_fallback"]
    else:
        methods = []
    plan = {"file": profile["path"], "methods": methods}
    _stage_log("plan_created", plan=plan)
    return plan


def _extract_via_plan(path: Path, plan: dict[str, Any], model: str = "gpt-4.1-mini") -> dict[str, Any]:
    attempts = []
    for method in plan["methods"]:
        _stage_log("extract_attempt", file=str(path), method=method)
        if method == "direct_text_read":
            text = path.read_text(encoding="utf-8")
        elif method == "docx_parse":
            text = _extract_text_from_docx(path)
        elif method == "digital_pdf_parse":
            text = _extract_text_from_digital_pdf(path)
        elif method == "ocr_pdf_fallback":
            parsed = json.loads(extract_text_from_scanned_pdf(path=str(path.relative_to(_resolve_file_ops_path())), model=model))
            text = parsed.get("text", "")
        else:
            continue

        quality = _quality_score(text)
        attempts.append({"method": method, "quality": quality})
        if quality["quality_ok"]:
            artifact = {
                "source_metadata": _classify_file(path),
                "extraction_method": method,
                "quality": quality,
                "extracted_text": text,
                "attempts": attempts,
            }
            _stage_log("extract_success", file=str(path), method=method, quality=quality)
            return artifact
        _stage_log("extract_fallback", file=str(path), method=method, quality=quality)

    raise ValueError(f"No extraction method met quality checks for {path}")


def _tool_with_logging(name: str):
    def decorator(fn: Any) -> Any:
        def wrapped(*args: Any, **kwargs: Any) -> str:
            tool_args = kwargs.copy()
            return _run_tool_with_logging(name, tool_args, lambda: fn(*args, **kwargs))

        return wrapped

    return decorator

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
@_tool_with_logging("weather")
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
@_tool_with_logging("query_db")
def query_db(sql: str) -> str:
    """Run a read-only SELECT query against local SQLite demo.db."""
    normalized = sql.strip().lower().rstrip(";")
    if not normalized.startswith("select"):
        raise ValueError("Only SELECT queries are allowed for this demo.")

    with _db_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return json.dumps([dict(r) for r in rows], indent=2)


@mcp.tool()
@_tool_with_logging("make_directory")
def make_directory(path: str) -> str:
    """Create a directory inside MCP_FILE_OPS_ROOT."""
    target = _resolve_file_ops_path(path)
    target.mkdir(parents=True, exist_ok=True)
    return f"Created directory: {target}"


@mcp.tool()
@_tool_with_logging("move_file")
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
@_tool_with_logging("move_files_by_glob")
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
@_tool_with_logging("list_files")
def list_files(path: str = ".") -> str:
    """List only files in a folder; for general content checks use list_directory_contents."""
    target = _resolve_file_ops_path(path)
    if not target.is_dir():
        raise ValueError(f"Not a directory: {target}")

    files = sorted(p.name for p in target.iterdir() if p.is_file())
    return json.dumps(files, indent=2)


@mcp.tool()
@_tool_with_logging("list_directories")
def list_directories(path: str = ".") -> str:
    """List only directories in a folder; for general content checks use list_directory_contents."""
    target = _resolve_file_ops_path(path)
    if not target.is_dir():
        raise ValueError(f"Not a directory: {target}")

    directories = sorted(p.name for p in target.iterdir() if p.is_dir())
    return json.dumps(directories, indent=2)


@mcp.tool()
@_tool_with_logging("list_directory_contents")
def list_directory_contents(path: str = ".") -> str:
    """Primary directory listing tool: return both files and directories in one response."""
    target = _resolve_file_ops_path(path)
    if not target.is_dir():
        raise ValueError(f"Not a directory: {target}")

    files = sorted(p.name for p in target.iterdir() if p.is_file())
    directories = sorted(p.name for p in target.iterdir() if p.is_dir())

    return json.dumps(
        {
            "path": str(target),
            "file_count": len(files),
            "directory_count": len(directories),
            "files": files,
            "directories": directories,
            "is_empty": len(files) == 0 and len(directories) == 0,
        },
        indent=2,
    )


@mcp.tool()
@_tool_with_logging("read_file")
def read_file(path: str) -> str:
    """Read a UTF-8 text file inside MCP_FILE_OPS_ROOT."""
    target = _resolve_file_ops_path(path)
    if not target.is_file():
        raise ValueError(f"File does not exist: {target}")
    return target.read_text(encoding="utf-8")


@mcp.tool()
@_tool_with_logging("inspect_file")
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
@_tool_with_logging("analyze_image_with_openai")
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
    def _impl() -> str:
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
                profile = _classify_file(file_path)
                plan = _build_extraction_plan(profile)
                artifact = _extract_via_plan(file_path, plan, model=model)
                text = artifact["extracted_text"]
                summary = _summarize_text_with_openai(text=text, prompt=prompt, model=model)
                summaries.append(
                    {
                        "path": str(file_path),
                        "file_name": file_path.name,
                        "summary": summary,
                        "char_count": len(text),
                        "artifact": {k: v for k, v in artifact.items() if k != "extracted_text"},
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
        _stage_log("task_run", task="summarize_documents_in_folder", processed_files=len(summaries))
        return json.dumps({
            "folder_path": str(folder),
            "max_files": max_files,
            "processed_files": len(summaries),
            "skipped_files": skipped_files,
            "per_file_summaries": summaries,
            "overall_summary": overall_summary,
        }, indent=2)

    return _run_tool_with_logging(
        tool_name="summarize_documents_in_folder",
        tool_args={"folder_path": folder_path, "prompt": prompt, "max_files": max_files, "model": model},
        fn=_impl,
    )



@mcp.tool()
def review_contract_language(path: str, focus: str | None = None, model: str = "gpt-4.1-mini") -> str:
    """Flag potentially misleading or risky contract language (not legal advice)."""

    def _impl() -> str:
        target = _resolve_file_ops_path(path)
        if not target.is_file():
            raise ValueError(f"File does not exist: {target}")
        if target.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
            raise ValueError("Supported file types: .txt, .md, .pdf, .docx")

        profile = _classify_file(target)
        plan = _build_extraction_plan(profile)
        artifact = _extract_via_plan(target, plan, model=model)
        text = artifact["extracted_text"]

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
        payload["artifact"] = {k: v for k, v in artifact.items() if k != "extracted_text"}
        _stage_log("task_run", task="review_contract_language", file=str(target))
        payload["disclaimer"] = "This review is automated and is not legal advice."
        return json.dumps(payload, indent=2)

    return _run_tool_with_logging(
        tool_name="review_contract_language",
        tool_args={"path": path, "focus": focus, "model": model},
        fn=_impl,
    )


@mcp.tool()
@_tool_with_logging("extract_text_from_scanned_pdf")
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
@_tool_with_logging("write_text_file")
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
