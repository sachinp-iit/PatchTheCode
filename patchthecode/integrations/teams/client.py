"""Microsoft Teams integration over an MCP connector.

Same contract as the Slack facade: a Teams MCP server is wrapped once and
message posts go through the server's advertised tools, aligned at runtime.
"""

from __future__ import annotations

from typing import Any

from patchthecode.integrations.names import align_tools
from patchthecode.mcp.client import MCPClient


class TeamsClient:
    """Facade over an MCP-backed Teams connector."""

    system = "teams"

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