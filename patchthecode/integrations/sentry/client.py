"""Sentry integration over an MCP connector.

Maps Sentry `list_events` hits onto `NormalizedOccurrence`. The exact tool
surface of a Sentry MCP server is a runtime detail; the default names follow
the common Sentry MCP servers and can be remapped via ``tool_names``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from patchthecode.detection.normalizer import NormalizedOccurrence, OccurrenceNormalizer
from patchthecode.domain import Severity
from patchthecode.mcp.client import MCPClient


class SentryNormalizer(OccurrenceNormalizer):
    """Map a Sentry event to a NormalizedOccurrence."""

    def normalize(self, payload: dict[str, Any]) -> NormalizedOccurrence:
        level = str(payload.get("level", "error")).lower()
        severity = Severity.CRITICAL if level in {"critical", "fatal"} else Severity.ERROR
        title = (
            payload.get("title")
            or payload.get("message")
            or f"{payload.get('type', 'sentry')} occurrence"
        )
        timestamp = datetime.fromisoformat(
            payload["dateCreated"]
        ) if payload.get("dateCreated") else datetime.utcnow()
        return NormalizedOccurrence(
            system="sentry",
            kind="errors",
            severity=severity,
            title=title,
            description=payload.get("culprit"),
            exception_type=(payload.get("metadata") or {}).get("type"),
            message=payload.get("message"),
            stack_trace=(payload.get("metadata") or {}).get("value"),
            timestamp=timestamp,
            service=(payload.get("tags") or {}).get("service"),
            raw=payload,
        )


class SentryClient:
    """Facade over an MCP-backed Sentry connector."""

    def __init__(self, mcp_client: MCPClient, tool_names: dict[str, str] | None = None) -> None:
        self.mcp = mcp_client
        self.normalizer = SentryNormalizer()
        self.tool_names = tool_names or {
            "list_events": "list_events",
            "search_issues": "search_issues",
        }

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()

    async def search_issues(self, query: str) -> list[NormalizedOccurrence]:
        """Search issues and normalize each hit."""
        result = await self.mcp.call_tool(self.tool_names["search_issues"], {"query": query})
        hits = result["structured"].get("issues", [])
        return [self.normalizer.normalize(hit) for hit in hits]

    async def list_events(self, issue_id: str) -> list[NormalizedOccurrence]:
        """Fetch events for an issue and normalize them."""
        result = await self.mcp.call_tool(self.tool_names["list_events"], {"issue_id": issue_id})
        hits = result["structured"].get("events", [])
        return [self.normalizer.normalize(hit) for hit in hits]