"""Tiny example using the OpenAI API + local MCP over HTTP.

Run the server first, then run this script in another terminal.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from openai import OpenAI


def main() -> None:
    # Load .env from current directory so OPENAI_API_KEY is available.
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY in your environment or .env file.")

    client = OpenAI(api_key=api_key)
    server_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")

    print(f"Using MCP server URL: {server_url}")

    response = client.responses.create(
        model="gpt-4.1-mini",
        input="Call the weather tool for Seattle and summarize in one sentence.",
        tools=[
            {
                "type": "mcp",
                "server_label": "local-mcp-demo",
                "server_url": server_url,
                "require_approval": "never",
            }
        ],
    )

    print(response.output_text)


if __name__ == "__main__":
    main()
