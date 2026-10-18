"""Pull new issues from an observability facade as an incident feed.

Implements the same `IncidentFeed` seam as `FileInbox` and the webhook queue,
so Sentry/Coralogix/App Insights can drive the watch loop directly: no file
drop and no webhook needed. Occurrences are fingerprinted through the same
detection path as everything else, so MCP-sourced incidents dedupe, learn, and
fast-path `already_fixed` identically.
"""

from __future__ import annotations

import logging
from typing import Any

from patchthecode.agent.sources import IncidentFeed
from patchthecode.detection.fingerprint import fingerprint
from patchthecode.detection.normalizer import NormalizedOccurrence, build_incident
from patchthecode.domain.models import Incident

logger = logging.getLogger(__name__)

# Sensible default action per facade system; callers can override.
DEFAULT_ACTIONS = {
    "sentry": "search_issues",
    "coralogix": "query_logs",
    "appinsights": "list_exceptions",
}


def default_action_for(facade: Any) -> str:
    """Pick the feed action that matches a facade's vendor."""
    system = str(getattr(facade, "system", "") or "").lower()
    return DEFAULT_ACTIONS.get(system, "search_issues")


class McpIssueFeed(IncidentFeed):
    """Poll an observability facade and yield new incidents by fingerprint.

    `execute` is the vendor-neutral seam every observability facade exposes,
    so one feed works for Sentry, Coralogix, and App Insights. The feed
    remembers which incident ids it has already handed out and skips them on
    the next poll; re-looked-up issues that the agent already recorded are
    still deduped by the store, but the feed itself avoids the noise.
    """

    def __init__(
        self,
        facade: Any,
        action: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        self.facade = facade
        self.action = action or default_action_for(facade)
        self.arguments = dict(arguments or {})
        self._handed_out: set[str] = set()

    async def fetch(self) -> list[Incident]:
        occurrences = await self.facade.execute(self.action, self.arguments)
        return self._incidents(occurrences)

    async def acknowledge(self, incident: Incident) -> None:
        self._handed_out.add(incident.id)

    def _incidents(self, occurrences: list[NormalizedOccurrence]) -> list[Incident]:
        """Group occurrences by fingerprint; each fingerprint becomes an incident."""
        grouped: dict[str, list[NormalizedOccurrence]] = {}
        for occurrence in occurrences:
            grouped.setdefault(fingerprint(occurrence).value, []).append(occurrence)
        incidents: list[Incident] = []
        for fingerprint_value, hits in grouped.items():
            first = min(hit.timestamp for hit in hits)
            last = max(hit.timestamp for hit in hits)
            incident = build_incident(
                occurrence=hits[0],
                fingerprint_value=fingerprint_value,
                occurrences=len(hits),
                first_seen=first,
                last_seen=last,
            )
            if incident.id in self._handed_out:
                continue
            incidents.append(incident)
        if incidents:
            logger.info(
                "mcp issue feed found %d new incident(s) via %s/%s",
                len(incidents),
                getattr(self.facade, "system", "?"),
                self.action,
            )
        return incidents
