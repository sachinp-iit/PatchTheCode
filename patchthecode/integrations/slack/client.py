"""Slack integration over an MCP connector.

A Slack MCP server (kind=communication) exposes tools that post to
channels. This facade maps those onto a single ``send_message`` surface,
aligned at runtime against the server's advertised tools so Slack's own
server, vendor servers, and eager proxies all work.
"""

from __future__ import annotations

from typing import Any

from patchthecode.integrations.names import align_tools
from patchthecode.mcp.client import MCPClient


class SlackClient:
    """Facade over an MCP-backed Slack connector."""

    system = "slack"

    def __init__(self, mcp_client: MCPClient, tool_names: dict[str, str] | None = None) -> None:
        self.mcp = mcp_client
        self._overrides = dict(tool_names or {})
        self._aligned: dict[str, str] | None = None

    async def _tool_names(self) -> dict[str, str]:
        if self._aligned is None:
            advertised = [str(t.get("name", "")) for t in await self.mcp.list_tools()]
            self._aligned = align_tools(self.system, advertised, self._overrides)
        return self._aligned

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()

    async def send_message(self, channel: str, text: str) -> bool:
        """Post a message to a channel; returns True when accepted."""
        names = await self._tool_names()
        await self.mcp.call_tool(
            names["send_message"],
            {"channel": channel or "#incidents", "text": text},
        )
        return True