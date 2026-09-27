"""Evidence collection during an investigation.

Evidence is collected from observability and git MCP connectors and passed
through redaction before anything is sent to an LLM or persisted. Plan steps
that target a recognized observability adapter are executed against the
*adapted* client so hits come back normalized; duplicates (same fingerprint)
collapse at the source so the analyzer never reasons over the same log line
hundreds of times. Steps a facade cannot normalize fall back to the raw
connector tool so the investigation still collects useful context.
"""

from __future__ import annotations

import logging
from typing import Any

from patchthecode.detection.fingerprint import fingerprint
from patchthecode.domain.models import Evidence, Incident
from patchthecode.integrations.errors import UnknownActionError
from patchthecode.integrations.factory import adapter_for
from patchthecode.investigation.planner import EvidencePlanItem, InvestigationPlanner
from patchthecode.mcp.redaction import Redactor

logger = logging.getLogger(__name__)


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
            facade = self._facade_for(client)
            try:
                entry = await self._execute(item, facade, client)
            except Exception:  # noqa: BLE001 - skip failing connectors, keep investigating
                continue
            if entry is None:
                logger.info("step %s/%s produced no evidence", item.connector, item.tool)
                continue
            evidence.append(entry)
        return evidence

    def _facade_for(self, client: Any) -> Any:
        """The adapted client for a connector, or None when not adaptable."""
        connection = getattr(client, "connection", None)
        if connection is None:
            return None
        try:
            return adapter_for(connection, client)
        except Exception:  # noqa: BLE001 - a strange connector stays raw
            logger.debug("could not build an adapter for %r; collecting raw", getattr(connection, "name", "?"))
            return None

    async def _execute(self, item: EvidencePlanItem, facade: Any, client: Any) -> Evidence | None:
        """Run one plan step, preferring the facade's normalized path.

        Recognized adapter actions return deduplicated occurrence evidence;
        everything else falls back to the raw connector payload so context
        steps (source, deployments, repository search) still contribute.
        """
        executor = getattr(facade, "execute", None)
        if executor is not None:
            try:
                occurrences = await executor(item.tool, item.arguments)
            except UnknownActionError:
                logger.debug("facade has no action %r; collecting raw", item.tool)
                occurrences = None
            if occurrences is not None:
                if not occurrences:
                    return None
                return self._from_occurrences(item, occurrences)
        raw = await client.call_tool(item.tool, item.arguments)
        return Evidence(
            kind=item.tool,
            source_system=item.connector,
            content=self.redactor.redact(raw),
        )

    def _from_occurrences(self, item: EvidencePlanItem, occurrences: list[Any]) -> Evidence:
        """Collapse identical occurrences to one fingerprint at the source."""
        grouped: dict[str, list[Any]] = {}
        order: list[str] = []
        for occurrence in occurrences:
            value = fingerprint(occurrence).value
            if value not in grouped:
                grouped[value] = []
                order.append(value)
            grouped[value].append(occurrence)
        unique = [grouped[value][0] for value in order]
        summaries = [
            self._summary(occurrence, value) for occurrence, value in zip(unique, order, strict=True)
        ]
        content = {
            "action": item.tool,
            "source_system": item.connector,
            "occurrence_count": len(occurrences),
            "unique_fingerprints": len(unique),
            "occurrences": summaries,
        }
        return Evidence(
            kind=item.tool,
            source_system=item.connector,
            content=self.redactor.redact(content),
            confidence=min(1.0, len(unique) / 20 + 0.5),
        )

    @staticmethod
    def _summary(occurrence: Any, fingerprint_value: str) -> dict[str, Any]:
        to_summary = getattr(occurrence, "to_summary", None)
        if to_summary is not None:
            return to_summary(fingerprint_value)
        return {"fingerprint": fingerprint_value, "payload": getattr(occurrence, "raw", occurrence)}