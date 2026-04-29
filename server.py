from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

DB_PATH = Path(os.getenv("MCP_DEMO_DB_PATH", "demo.db"))

mcp = FastMCP("local-mcp-demo")


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


def main() -> None:
    _bootstrap_db()
    mcp.run()


if __name__ == "__main__":
    main()
