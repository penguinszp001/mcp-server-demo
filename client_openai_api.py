"""Tiny example using the OpenAI API + local MCP over HTTP.

Run the server first, then run this script in another terminal.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

from openai import APIStatusError, OpenAI


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

        try:
            response = client.responses.create(
                model="gpt-4.1-mini",
                input=user_query,
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

        print(response.output_text)


if __name__ == "__main__":
    main()
