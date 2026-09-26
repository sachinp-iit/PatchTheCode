"""Evidence collection during an investigation.

Evidence is collected from observability and git MCP connectors and passed
through redaction before anything is sent to an LLM or persisted.
"""

from __future__ import annotations

from typing import Any

from patchthecode.domain.models import Evidence, Incident
from patchthecode.investigation.planner import InvestigationPlanner
from patchthecode.mcp.redaction import Redactor


class EvidenceCollector:
    """Coordinates evidence gathering across configured MCP connectors.

    The set of evidence to collect is decided by the InvestigationPlanner
    (LLM-driven with a deterministic fallback). Connector/tool calls that
    fail are skipped so a single flaky system does not abort the rest of
    the investigation.
    """

    def __init__(
        self,
        planner: InvestigationPlanner | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self.planner = planner or InvestigationPlanner()
        self.redactor = redactor or Redactor()

    async def collect(self, incident: Incident, connectors: dict[str, Any]) -> list[Evidence]:
        evidence: list[Evidence] = []
        for item in await self.planner.plan(incident, connectors):
            client = connectors.get(item.connector)
            if client is None:
                continue
            try:
                raw = await client.call_tool(item.tool, item.arguments)
            except Exception:  # noqa: BLE001 - skip failing connectors, keep investigating
                continue
            evidence.append(
                Evidence(
                    kind=item.tool,
                    source_system=item.connector,
                    content=self.redactor.redact(raw),
                )
            )
        return evidence