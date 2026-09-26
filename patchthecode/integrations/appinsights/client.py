"""Azure Application Insights integration over an MCP connector.

App Insights data arrives as log/trace/exception query results; the
normalizer maps a single row onto ``NormalizedOccurrence`` so the detection
pipeline can reason about it like any other system's occurrence. Tool names
are aligned against the server's advertised tools (``integrations.names``);
``tool_names`` overrides win.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from patchthecode.detection.normalizer import NormalizedOccurrence, OccurrenceNormalizer
from patchthecode.domain import Severity
from patchthecode.integrations.names import align_tools
from patchthecode.mcp.client import MCPClient


class AppInsightsNormalizer(OccurrenceNormalizer):
    """Map an App Insights trace/exception row to a NormalizedOccurrence."""

    def normalize(self, payload: dict[str, Any]) -> NormalizedOccurrence:
        severity_value = payload.get("severityLevel")
        severity = (
            Severity.CRITICAL
            if severity_value in {4, 5}
            else Severity.ERROR
            if severity_value in {3, None}
            else Severity.WARNING
        )
        title = (
            payload.get("message")
            or payload.get("exceptionType")
            or payload.get("name")
            or "appinsights occurrence"
        )
        timestamp = payload.get("timestamp")
        if isinstance(timestamp, str):
            parsed = datetime.fromisoformat(timestamp)
        elif isinstance(timestamp, datetime):
            parsed = timestamp
        else:
            parsed = datetime.utcnow()
        return NormalizedOccurrence(
            system="appinsights",
            kind="traces",
            severity=severity,
            title=title,
            description=payload.get("operation_Name"),
            exception_type=payload.get("exceptionType") or payload.get("exception_type"),
            message=payload.get("message"),
            stack_trace=payload.get("stackTrace") or payload.get("outerExceptionMessage"),
            timestamp=parsed,
            service=payload.get("cloud_RoleName") or payload.get("service"),
            raw=payload,
        )


class AppInsightsClient:
    """Facade over an MCP-backed Application Insights connector."""

    system = "appinsights"

    def __init__(self, mcp_client: MCPClient, tool_names: dict[str, str] | None = None) -> None:
        self.mcp = mcp_client
        self.normalizer = AppInsightsNormalizer()
        self._overrides = dict(tool_names or {})
        self._aligned: dict[str, str] | None = None

    async def _tool_names(self) -> dict[str, str]:
        if self._aligned is None:
            advertised = [str(t.get("name", "")) for t in await self.mcp.list_tools()]
            self._aligned = align_tools(self.system, advertised, self._overrides)
        return self._aligned

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.mcp.list_tools()

    async def query(self, query: str) -> list[NormalizedOccurrence]:
        """Run a KQL-style query and normalize every returned row."""
        names = await self._tool_names()
        result = await self.mcp.call_tool(names["query"], {"query": query})
        rows = result["structured"].get("rows", result["structured"].get("tables", []))
        return [self.normalizer.normalize(row) for row in rows]

    async def list_exceptions(self, operation_id: str | None = None) -> list[NormalizedOccurrence]:
        """Fetch recent exceptions for an operation, normalized."""
        names = await self._tool_names()
        arguments: dict[str, Any] = {}
        if operation_id:
            arguments["operation_id"] = operation_id
        result = await self.mcp.call_tool(names["list_exceptions"], arguments)
        rows = result["structured"].get("events", [])
        return [self.normalizer.normalize(row) for row in rows]