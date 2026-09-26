"""GitLab integration over an MCP connector.

GitLab exposes the same *surface* PatchTheCode needs — fetch a file, create
a branch, commit, open a merge request — so ``GitLabClient`` reuses the
GitHub write path and only resolves a GitLab-shaped tool map: merge-request
tools are preferred, project search rather than repository search. Tool
variations across GitLab MCP servers are handled by runtime alignment
(``integrations.names``); ``tool_names`` overrides stay verbatim.
"""

from __future__ import annotations

from typing import Any

from patchthecode.integrations.github.client import GitHubClient
from patchthecode.mcp.client import MCPClient


class GitLabClient(GitHubClient):
    """Facade over an MCP-backed GitLab connector (MR-flavored git client)."""

    system = "gitlab"

    def __init__(
        self,
        mcp_client: MCPClient,
        tool_names: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mcp_client, tool_names=tool_names, system=self.system)

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()