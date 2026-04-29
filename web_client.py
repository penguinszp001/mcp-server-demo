"""Simple web chat UI for OpenAI Responses API + MCP tools."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv
from openai import APIStatusError, OpenAI

load_dotenv()

st.set_page_config(page_title="MCP Chat Client", page_icon="💬", layout="centered")
st.title("💬 MCP Chat Client")
st.caption("Ask questions and let the model call your MCP server tools.")

api_key = os.getenv("OPENAI_API_KEY")
server_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

if not api_key:
    st.error("OPENAI_API_KEY is not set. Add it to your environment or .env file.")
    st.stop()

parsed = urlparse(server_url)
if parsed.hostname in {"127.0.0.1", "localhost"}:
    st.warning(
        "If this request is handled by OpenAI-hosted infrastructure, localhost/127.0.0.1 "
        "is not reachable. Use a public MCP_SERVER_URL tunnel if needed."
    )

client = OpenAI(api_key=api_key)

if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.subheader("Settings")
    st.write(f"**Model:** `{model}`")
    st.write(f"**MCP server:** `{server_url}`")
    if st.button("Clear chat history"):
        st.session_state.messages = []
        st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Type your question...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response = client.responses.create(
                    model=model,
                    input=st.session_state.messages,
                    tools=[
                        {
                            "type": "mcp",
                            "server_label": "mcp-server-demo",
                            "server_url": server_url,
                            "require_approval": "never",
                        }
                    ],
                )
                answer = response.output_text or "(No text response returned.)"
            except APIStatusError as err:
                answer = (
                    f"OpenAI API error: {err}\n\n"
                    "Troubleshooting:\n"
                    "1) Ensure server is running with MCP_TRANSPORT=streamable-http.\n"
                    "2) Ensure MCP_SERVER_URL exactly matches host/port/path.\n"
                    "3) If using OpenAI-hosted API calls, localhost/127.0.0.1 is not reachable; "
                    "use a public tunnel URL for MCP_SERVER_URL."
                )

        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
