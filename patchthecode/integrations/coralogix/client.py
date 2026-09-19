"""Coralogix integration over an MCP connector.

The actual Coralogix access happens through the configured MCP server that
exposes Coralogix tools (query logs, list deployments, exception groups).
This module knows the expected tool names, maps results onto `OccurrenceNormalizer`,
and hides Coralogix specifics from the agent core.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from patchthecode.detection.normalizer import NormalizedOccurrence, OccurrenceNormalizer
from patchthecode.domain import Severity
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

    def __init__(self, mcp_client: MCPClient) -> None:
        self.mcp = mcp_client
        self.normalizer = CoralogixNormalizer()

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()

    async def query_logs(self, query: str, time_range: dict[str, str]) -> list[NormalizedOccurrence]:
        """Search logs and normalize every hit.

        TODO: confirm the real tool name/args exposed by the Coralogix MCP
        server (`query_logs` is a placeholder). Also request only the fields
        the agent needs to keep payloads small.
        """
        result = await self.mcp.call_tool("query_logs", {"query": query, "time_range": time_range})
        hits = result["structured"].get("hits", [])
        return [self.normalizer.normalize(hit) for hit in hits]

    async def list_deployments(self, service: str, time_range: dict[str, str]) -> list[dict[str, Any]]:
        """Return deployment events for correlation to code changes."""
        result = await self.mcp.call_tool("list_deployments", {"service": service, "time_range": time_range})
        return result["structured"].get("deployments", [])