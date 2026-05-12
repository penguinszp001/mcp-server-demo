"""Tiny example using the OpenAI API + local MCP over HTTP.

Run the server first, then run this script in another terminal.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from openai import APIStatusError, OpenAI

CALENDAR_SYSTEM_INSTRUCTION = (
    "For list_google_calendar_events, always provide explicit RFC3339 time_min and time_max in "
    "America/New_York. If user does not provide a window, use now through end of current week "
    "(Sunday 23:59:59.999) in America/New_York. Resolve vague windows like 'next week', 'this week', "
    "'tomorrow', and 'upcoming' into explicit time_min/time_max before calling tools. Present all "
    "calendar references and summaries in Eastern Time."
)


CLIENT_LOG_PATH = Path(os.getenv("MCP_CLIENT_LOG_PATH", "mcp_client_events.jsonl"))


def _log_client_event(event: dict) -> None:
    event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    CLIENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False)
    with CLIENT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(f"[mcp-client-log] {line}")


def _log_response_details(response: object) -> None:
    for item in getattr(response, "output", []) or []:
        item_type = getattr(item, "type", "unknown")
        details = {"event": "response_output", "item_type": item_type}
        if hasattr(item, "name"):
            details["name"] = getattr(item, "name")
        if hasattr(item, "id"):
            details["id"] = getattr(item, "id")
        if hasattr(item, "arguments"):
            details["arguments"] = getattr(item, "arguments")
        if hasattr(item, "error") and getattr(item, "error"):
            details["error"] = getattr(item, "error")
        _log_client_event(details)

def main() -> None:
    # Load .env from current directory so OPENAI_API_KEY is available.
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY in your environment or .env file.")

    client = OpenAI(api_key=api_key)
    server_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")

    print(f"Using MCP server URL: {server_url}")
    parsed = urlparse(server_url)
    if parsed.hostname in {"127.0.0.1", "localhost"}:
        print(
            "Warning: if this request is handled by OpenAI-hosted infrastructure, "
            "localhost/127.0.0.1 is not reachable. Use a tunnel/public URL for MCP_SERVER_URL."
        )

    print("Enter a prompt to send to the model (type 'exit' to quit).")

    while True:
        user_query = input("\nQuery: ").strip()
        if user_query.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        if not user_query:
            print("Please enter a non-empty query.")
            continue

        _log_client_event({"event": "prompt_submitted", "prompt": user_query, "server_url": server_url})

        try:
            response = client.responses.create(
                model="gpt-4.1-mini",
                input=[
                    {"role": "system", "content": CALENDAR_SYSTEM_INSTRUCTION},
                    {"role": "user", "content": user_query},
                ],
                tools=[
                    {
                        "type": "mcp",
                        "server_label": "mcp-server-demo",
                        "server_url": server_url,
                        "require_approval": "never",
                    }
                ],
            )
        except APIStatusError as err:
            _log_client_event({"event": "api_error", "error": str(err)})
            print(f"OpenAI API error: {err}")
            print()
            print("Troubleshooting:")
            print("1) Ensure server is running with MCP_TRANSPORT=streamable-http.")
            print("2) Ensure MCP_SERVER_URL exactly matches host/port/path.")
            print(
                "3) If using OpenAI-hosted API calls, localhost/127.0.0.1 is not reachable; "
                "use a public tunnel URL for MCP_SERVER_URL."
            )
            continue

        _log_client_event({"event": "response_text", "output_text": response.output_text})
        _log_response_details(response)
        print(response.output_text)


if __name__ == "__main__":
    main()
