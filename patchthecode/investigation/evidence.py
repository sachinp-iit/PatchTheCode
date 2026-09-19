"""Evidence collection during an investigation.

Evidence is collected from observability and git MCP connectors and passed
through redaction before anything is sent to an LLM or persisted.
"""

from __future__ import annotations

from typing import Any

from patchthecode.domain.models import Evidence, Incident
from patchthecode.mcp.redaction import Redactor


class EvidenceCollector:
    """Coordinates evidence gathering across configured MCP connectors.

    TODO: define the evidence plan (what to collect and in what order) and
    per-connector query builders. Sketch of the flow:

        observability -> logs/errors/traces around incident.first_seen
        observability -> deployments for affected service
        git           -> commits touching resolved files around deploy time
        git           -> source snippets at the resolved location
    """

    def __init__(self, redactor: Redactor | None = None) -> None:
        self.redactor = redactor or Redactor()

    async def collect(self, incident: Incident, connectors: dict[str, Any]) -> list[Evidence]:
        evidence: list[Evidence] = []
        for name, tool_name, args in self._plan(incident):
            client = connectors.get(name)
            if client is None:
                continue
            try:
                raw = await client.call_tool(tool_name, args)
            except Exception:  # noqa: BLE001
                continue
            evidence.append(
                Evidence(
                    kind=tool_name,
                    source_system=name,
                    content=self.redactor.redact(raw),
                )
            )
        return evidence

    def _plan(self, incident: Incident) -> list[tuple[str, str, dict[str, Any]]]:
        """Resolve which connector/tool to call for this incident.

        TODO: make this planner-driven (see llm/prompts.investigate_incident_prompt).
        Until then, a hardcoded stub keeps the vertical slice wired.
        """
        service = (incident.raw.get("service") or "") if incident.raw else ""
        window = {
            "from": incident.first_seen.isoformat(),
            "to": incident.last_seen.isoformat(),
            "service": service,
        }
        plan = []
        if service:
            plan.append(("coralogix_mcp", "query_logs", dict(window)))
            plan.append(("coralogix_mcp", "list_deployments", dict(window)))
        plan.append(("github_mcp", "search_repository", {"service": service or incident.fingerprint}))
        return plan