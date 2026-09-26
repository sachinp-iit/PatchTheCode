"""GitHub integration over an MCP connector.

Repository search, file/commit resolution, branch creation, and PR creation
all flow through the configured GitHub MCP server. This module maps those
operations onto the tools PatchTheCode needs; it never talks to GitHub
directly.

Tool names follow the standard github-mcp-server surface
(``get_file_contents``, ``create_branch``, ``create_commit``,
``create_pull_request``). Remap ``tool_names`` to match a different server.
"""

from __future__ import annotations

import logging
from typing import Any

from patchthecode.domain.models import CodeLocation, PullRequestData, PullRequestResult
from patchthecode.mcp.client import MCPClient
from patchthecode.remediation.patch import PatchError, apply_unified_diff, diff_for_file

logger = logging.getLogger(__name__)


class GitHubClient:
    """Facade over an MCP-backed GitHub connector."""

    def __init__(
        self,
        mcp_client: MCPClient,
        tool_names: dict[str, str] | None = None,
    ) -> None:
        self.mcp = mcp_client
        self.tool_names = tool_names or {
            "search_repositories": "search_repositories",
            "get_content": "get_file_contents",
            "create_branch": "create_branch",
            "create_commit": "create_commit",
            "create_pr": "create_pull_request",
            "get_pr": "get_pull_request",
        }

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()

    async def search_repository(self, query: str) -> list[dict[str, Any]]:
        result = await self.mcp.call_tool(self.tool_names["search_repositories"], {"query": query})
        return result["structured"].get("repositories", [])

    async def resolve_file(self, location: CodeLocation) -> str:
        """Fetch source for a resolved location."""
        result = await self.mcp.call_tool(
            self.tool_names["get_content"],
            {"repository": location.repository, "path": location.file_path or ""},
        )
        return result["content"]

    async def open_pull_request(self, data: PullRequestData) -> PullRequestResult:
        """Open a PR: apply the diff to current sources, create a branch, commit, and PR.

        Safe by construction: it only writes through the MCP git tools and
        only after the caller has passed the human-review gate.
        """
        owner, repo_name = self._split_repo(data.repository)

        new_files = await self._patched_files(data, owner, repo_name)
        await self.mcp.call_tool(
            self.tool_names["create_branch"],
            {"owner": owner, "repo": repo_name, "branch": data.head_branch},
        )
        if new_files:
            await self.mcp.call_tool(
                self.tool_names["create_commit"],
                {
                    "owner": owner,
                    "repo": repo_name,
                    "message": data.title,
                    "files": new_files,
                    "branch": data.head_branch,
                },
            )
        result = await self.mcp.call_tool(
            self.tool_names["create_pr"],
            {
                "owner": owner,
                "repo": repo_name,
                "title": data.title,
                "body": data.description,
                "head": data.head_branch,
                "base": data.base_branch,
            },
        )
        structured = result.get("structured") or {}
        url = structured.get("url") or structured.get("html_url") or ""
        try:
            number = int(structured.get("number") or 0)
        except (TypeError, ValueError):
            number = 0
        return PullRequestResult(url=url, number=number, state="open")

    async def get_pull_request(self, pr: PullRequestResult, repository: str) -> str:
        """Poll the review state of a PR: "open", "merged", or "closed"."""
        owner, repo_name = self._split_repo(repository)
        result = await self.mcp.call_tool(
            self.tool_names["get_pr"],
            {"owner": owner, "repo": repo_name, "number": pr.number},
        )
        payload = result.get("structured") or {}
        merged = payload.get("merged", False)
        state = str(payload.get("state", "open"))
        if merged is True or state == "merged":
            return "merged"
        if state == "closed":
            return "closed"
        return "open"

    async def _patched_files(self, data: PullRequestData, owner: str, repo_name: str) -> list[dict[str, str]]:
        """Build {path, content} pairs for every file touched by the fix diff."""
        new_files: list[dict[str, str]] = []
        for path in data.files:
            file_diff = diff_for_file(data.diff, path)
            if not file_diff:
                continue
            fetched = await self.mcp.call_tool(
                self.tool_names["get_content"],
                {
                    "owner": owner,
                    "repo": repo_name,
                    "path": path,
                    "branch": data.base_branch,
                },
            )
            original = fetched["content"]
            try:
                content = apply_unified_diff(original, file_diff)
            except PatchError:
                logger.warning("could not apply fix %r to %s; leaving it to the PR review", data.title, path)
                raise
            new_files.append({"path": path, "content": content})
        return new_files

    @staticmethod
    def _split_repo(repository: str) -> tuple[str, str]:
        if "/" in repository:
            owner, _, name = repository.partition("/")
            return owner.strip(), name.strip()
        return repository.strip(), repository.strip()