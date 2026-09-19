"""GitHub integration over an MCP connector.

Repository search, file/commit resolution, branch creation, and PR creation
all flow through the configured GitHub MCP server. This module maps those
operations onto the tools PatchTheCode needs; it never talks to GitHub
directly.
"""

from __future__ import annotations

from typing import Any

from patchthecode.domain.models import CodeLocation, PullRequestData, PullRequestResult
from patchthecode.mcp.client import MCPClient


class GitHubClient:
    """Facade over an MCP-backed GitHub connector."""

    def __init__(self, mcp_client: MCPClient) -> None:
        self.mcp = mcp_client

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()

    async def search_repository(self, query: str) -> list[dict[str, Any]]:
        result = await self.mcp.call_tool("search_repositories", {"query": query})
        return result["structured"].get("repositories", [])

    async def resolve_file(self, location: CodeLocation) -> str:
        """Fetch source for a resolved location."""
        result = await self.mcp.call_tool(
            "get_content", {"repository": location.repository, "path": location.file_path or ""}
        )
        return result["content"]

    async def open_pull_request(self, data: PullRequestData) -> PullRequestResult:
        """Open a PR; raises NotImplementedError until the git write path is wired.

        TODO: implement branch create + commit + push + PR create through the
        GitHub MCP tools, behind the human-review safety gate.
        """
        raise NotImplementedError("open_pull_request is not implemented yet.")