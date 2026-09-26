"""Coralogix integration over an MCP connector.

The actual Coralogix access happens through the configured MCP server that
exposes Coralogix tools (query logs, list deployments, exception groups).
This module knows the expected tool surface, maps results onto
`OccurrenceNormalizer`, and hides Coralogix specifics from the agent core.
Tool names are aligned against the server's advertised tools
(``integrations.names``); ``tool_names`` overrides win.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from patchthecode.detection.normalizer import NormalizedOccurrence, OccurrenceNormalizer
from patchthecode.domain import Severity
from patchthecode.integrations.names import align_tools
from patchthecode.mcp.client import MCPClient


class CoralogixNormalizer(OccurrenceNormalizer):
    """Map a Coralogix search hit to a NormalizedOccurrence.

    TODO: expand for the real Coralogix MCP response shape.
    """

    def normalize(self, payload: dict[str, Any]) -> NormalizedOccurrence:
        severity = Severity.CRITICAL if payload.get("severity") == 5 else Severity.ERROR
        return NormalizedOccurrence(
            system="coralogix",
            kind="logs",
            severity=severity,
            title=payload.get("text") or payload.get("message") or "coralogix occurrence",
            description=payload.get("threadId"),
            exception_type=payload.get("exceptionType"),
            message=payload.get("message") or payload.get("text"),
            stack_trace=payload.get("stacktrace") or payload.get("stackTrace"),
            timestamp=datetime.utcnow(),
            service=payload.get("applicationName") or payload.get("service"),
            raw=payload,
        )


class CoralogixClient:
    """Facade over an MCP-backed Coralogix connector."""

    system = "coralogix"

    def __init__(self, mcp_client: MCPClient, tool_names: dict[str, str] | None = None) -> None:
        self.mcp = mcp_client
        self.normalizer = CoralogixNormalizer()
        self._overrides = dict(tool_names or {})
        self._aligned: dict[str, str] | None = None

    async def _tool_names(self) -> dict[str, str]:
        if self._aligned is None:
            advertised = [str(t.get("name", "")) for t in await self.mcp.list_tools()]
            self._aligned = align_tools(self.system, advertised, self._overrides)
        return self._aligned

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()

    async def query_logs(self, query: str, time_range: dict[str, str]) -> list[NormalizedOccurrence]:
        """Search logs and normalize every hit."""
        names = await self._tool_names()
        result = await self.mcp.call_tool(names["query_logs"], {"query": query, "time_range": time_range})
        hits = result["structured"].get("hits", [])
        return [self.normalizer.normalize(hit) for hit in hits]

    async def list_deployments(self, service: str, time_range: dict[str, str]) -> list[dict[str, Any]]:
        """Return deployment events for correlation to code changes."""
        names = await self._tool_names()
        result = await self.mcp.call_tool(
            names["list_deployments"], {"service": service, "time_range": time_range}
        )
        return result["structured"].get("deployments", [])