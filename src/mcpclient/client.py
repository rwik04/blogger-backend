"""Thin wrapper around the official Python MCP SDK (`mcp` package) for the
Exa MCP server. No LangChain adapter layer — our graph nodes call
`MCPClient.call_tool(...)` directly.

(Named `mcpclient`, not `mcp`, to avoid shadowing the `mcp` pip package.)

Usage:
    async with get_exa_client() as exa:
        result = await exa.call_tool("web_search_exa", {"query": "..."})
"""

from __future__ import annotations

import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent


class MCPClient:
    """One stdio subprocess + one MCP session, kept alive for the lifetime of
    the `async with` block — a single Researcher run opens one of these and
    reuses it across every search/scrape call in that run (multiple rounds
    included), rather than paying subprocess-startup cost per tool call.
    """

    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None) -> None:
        self._params = StdioServerParameters(command=command, args=args, env=env)
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "MCPClient":
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(self._params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        if self._session is None:
            raise RuntimeError("MCPClient must be used as an async context manager before call_tool()")
        return await self._session.call_tool(name, arguments)


def get_exa_client() -> MCPClient:
    """Builds (but doesn't yet connect) an `MCPClient` for Exa's `exa-mcp-server`.

    Exa ships their MCP server as an npm package, run over stdio via `npx`.
    Swapping to a different search provider or a self-hosted MCP server later
    is a one-function change here — nothing in the Researcher graph nodes
    talks to Exa directly, they only call `MCPClient.call_tool(...)`.
    """
    api_key = os.environ["EXA_API_KEY"]
    return MCPClient(
        command="npx",
        args=["-y", "exa-mcp-server"],
        env={**os.environ, "EXA_API_KEY": api_key},
    )


def extract_text(result: CallToolResult) -> str:
    """Concatenates the plain-text parts of a tool result. Exa's tools return
    human-readable text (and sometimes `structuredContent`); most of our
    parsing prefers `structuredContent` when present (see
    `agents/researcher/nodes/search.py`) and falls back to this for
    freeform/legacy responses.
    """
    parts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join(parts)
