"""LLM-driven evidence planning for an incident.

The planner turns an incident into an ordered list of connector/tool calls.
When no model is configured (or the LLM call fails), it falls back to a
safe default plan so the pipeline still produces evidence in demo/skeleton
deployments instead of failing silently.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from patchthecode.domain.models import Incident
from patchthecode.llm.gateway import LLMGateway
from patchthecode.llm.prompts import evidence_plan_prompt

logger = logging.getLogger(__name__)


class EvidencePlanItem(BaseModel):
    """One step of an evidence plan."""

    connector: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str = ""


class InvestigationPlanner:
    """Produce evidence plans, preferring LLM guidance with a fallback."""

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway

    async def plan(self, incident: Incident, connectors: dict[str, Any]) -> list[EvidencePlanItem]:
        tool_catalog = await self._build_tool_catalog(connectors)
        items = await self._llm_plan(incident, connectors, tool_catalog)
        if items is None:
            return self.fallback_plan(incident)
        return self._select_known_connectors(items, connectors, tool_catalog)

    async def _build_tool_catalog(self, connectors: dict[str, Any]) -> dict[str, set[str] | None]:
        """Tool names per connector; None when listing failed (no tool filter)."""
        catalog: dict[str, set[str] | None] = {}
        for name, client in connectors.items():
            try:
                tools = await client.list_tools()
                catalog[name] = {t["name"] for t in tools}
            except Exception:  # noqa: BLE001 - cannot afford to fail planning over a flaky catalog
                catalog[name] = None
        return catalog

    async def _llm_plan(
        self,
        incident: Incident,
        connectors: dict[str, Any],
        tool_catalog: dict[str, set[str] | None],
    ) -> list[EvidencePlanItem] | None:
        if self.gateway is None:
            return None
        catalog = [
            {
                "name": name,
                "kind": getattr(client.connection, "kind", "unknown"),
                "tools": sorted(tool_catalog[name] or []),
            }
            for name, client in connectors.items()
        ]
        messages = evidence_plan_prompt(incident.model_dump(mode="json"), catalog)
        try:
            data = await self.gateway.complete_json("investigation", messages)
        except Exception:  # noqa: BLE001 - fall back when the model is unreachable
            logger.warning("LLM evidence planning failed; using fallback plan", exc_info=True)
            return None
        try:
            return [EvidencePlanItem.model_validate(step) for step in data.get("steps", [])]
        except (ValueError, TypeError, ValidationError) as exc:
            logger.warning("LLM returned an invalid evidence plan: %s", exc)
            return None

    def _select_known_connectors(
        self,
        items: list[EvidencePlanItem],
        connectors: dict[str, Any],
        tool_catalog: dict[str, set[str] | None],
    ) -> list[EvidencePlanItem]:
        kept: list[EvidencePlanItem] = []
        for item in items:
            if item.connector not in connectors:
                logger.warning("planner referenced unknown connector %r; dropping step", item.connector)
                continue
            known_tools = tool_catalog.get(item.connector)
            if known_tools is not None and item.tool not in known_tools:
                logger.warning("planner referenced unknown tool %r; dropping step", item.tool)
                continue
            kept.append(item)
        return kept

    def fallback_plan(self, incident: Incident) -> list[EvidencePlanItem]:
        """Deterministic plan used when no model is available."""
        service = (incident.raw.get("service") or "") if incident.raw else ""
        window = {
            "from": incident.first_seen.isoformat(),
            "to": incident.last_seen.isoformat(),
            "service": service,
        }
        steps = []
        if service:
            steps.append(
                EvidencePlanItem(
                    connector="coralogix_mcp",
                    tool="query_logs",
                    arguments=dict(window),
                    purpose="logs around the incident window for the affected service",
                )
            )
            steps.append(
                EvidencePlanItem(
                    connector="coralogix_mcp",
                    tool="list_deployments",
                    arguments=dict(window),
                    purpose="deployments that could have introduced the incident",
                )
            )
        steps.append(
            EvidencePlanItem(
                connector="github_mcp",
                tool="search_repository",
                arguments={"service": service or incident.fingerprint},
                purpose="locate the repository for the affected service",
            )
        )
        return steps