"""CI integration over an MCP connector.

A CI MCP server exposes tools that submit work to the pipeline (create a
check run for a proposed diff) and report its results. This facade maps
those onto the shapes PatchTheCode's validation runner expects. Tool names
follow common CI MCP servers, aligned at runtime against the server's
advertised tools (``integrations.names``); ``tool_names`` overrides win.
"""

from __future__ import annotations

from typing import Any

from patchthecode.integrations.names import align_tools
from patchthecode.mcp.client import MCPClient


class CIClient:
    """Facade over an MCP-backed CI connector."""

    system = "ci"

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

    async def submit_check(self, repository: str, diff: str, branch: str | None = None) -> str:
        """Ask CI to evaluate a proposed diff; returns a check reference."""
        names = await self._tool_names()
        result = await self.mcp.call_tool(
            names["create_check_run"],
            {"repository": repository, "diff": diff, "branch": branch or "HEAD"},
        )
        structured = result.get("structured") or {}
        return str(structured.get("check_ref") or structured.get("id") or "")

    async def poll_checks(self, check_ref: str) -> list[dict[str, str]]:
        """Return the outcome of a check run as [{name, status}]."""
        names = await self._tool_names()
        result = await self.mcp.call_tool(names["get_check_run"], {"check_ref": check_ref})
        structured = result.get("structured") or {}
        rows = structured.get("checks") or structured.get("check_runs") or []
        if not rows and structured.get("status"):
            rows = [{"name": structured.get("name", "ci"), "status": structured.get("status")}]
        return [
            {"name": str(row.get("name", "ci")), "status": str(row.get("status", "unknown"))}
            for row in rows
        ]