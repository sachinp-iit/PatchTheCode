"""Thin client over the official MCP Python SDK.

Supports stdio and streamable-http transports. Keeps the rest of
PatchTheCode agnostic to the underlying transport.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from patchthecode.config import MCPConnection


class MCPToolError(RuntimeError):
    """Raised when an MCP tool call fails."""


class MCPClient:
    """Connect to a single MCP server and expose tool listing/calling."""

    def __init__(self, connection: MCPConnection) -> None:
        self.connection = connection
        self._session: ClientSession | None = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        async with self._transport() as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    @asynccontextmanager
    async def _transport(self) -> AsyncIterator[tuple[Any, Any]]:
        conn = self.connection
        if conn.transport == "stdio":
            if not conn.command:
                raise MCPToolError(f"stdio connection {conn.name!r} has no command configured")
            params = StdioServerParameters(command=conn.command, args=conn.args, env=conn.env or None)
            async with stdio_client(params) as streams:
                yield streams
        elif conn.transport == "streamable-http":
            if not conn.url:
                raise MCPToolError(f"http connection {conn.name!r} has no url configured")
            async with streamable_http_client(conn.url) as streams:
                yield streams
        else:
            raise MCPToolError(f"unsupported transport {conn.transport!r} for {conn.name!r}")

    async def list_tools(self) -> list[dict[str, Any]]:
        async with self.session() as session:
            tools = await session.list_tools()
            return [{"name": t.name, "description": t.description, "schema": t.input_schema} for t in tools.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self.session() as session:
            result = await session.call_tool(name, arguments or {})
            if result.is_error:
                detail = result.content[0].text if result.content and isinstance(result.content[0], TextContent) else "no error detail"
                raise MCPToolError(f"tool {name!r} failed: {detail}")
            text_parts = [c.text for c in result.content if isinstance(c, TextContent)]
            structured = result.structured_content or {}
            return {"content": "\n".join(text_parts), "structured": structured}