"""GitLab integration over an MCP connector.

GitLab exposes the same *surface* PatchTheCode needs — fetch a file, create
a branch, commit, open a merge request — so ``GitLabClient`` reuses the
GitHub write path and only swaps the tool-name map to a GitLab MCP server's
tool names. Remap ``tool_names`` to match whatever GitLab server is in use.
"""

from __future__ import annotations

from typing import Any

from patchthecode.integrations.github.client import GitHubClient
from patchthecode.mcp.client import MCPClient


class GitLabClient(GitHubClient):
    """Facade over an MCP-backed GitLab connector (MR-flavored git client)."""

    def __init__(
        self,
        mcp_client: MCPClient,
        tool_names: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            mcp_client,
            tool_names=tool_names
            or {
                "search_repositories": "search_projects",
                "get_content": "get_file_contents",
                "create_branch": "create_branch",
                "create_commit": "create_commit",
                "create_pr": "create_merge_request",
            },
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()