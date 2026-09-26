"""Agent core: orchestrates detect → investigate → remediate → notify.

This is a working skeleton. Each step delegates to a module; steps that are
not yet implemented raise clearly and leave the report partially filled so
the top-level loop stays honest about what happened.
"""

from __future__ import annotations

import logging

from patchthecode.domain.models import CodeLocation, InvestigationReport, RootCause
from patchthecode.investigation.evidence import EvidenceCollector
from patchthecode.investigation.planner import InvestigationPlanner
from patchthecode.llm.gateway import LLMGateway
from patchthecode.notifications.notifier import Notifier
from patchthecode.remediation.fixer import FixGenerator
from patchthecode.repository.discovery import RepositoryDiscovery
from patchthecode.storage.store import Store
from patchthecode.validation.runner import ValidationRunner

logger = logging.getLogger(__name__)


class Agent:
    """Top-level orchestration loop for one incident."""

    def __init__(
        self,
        *,
        gateway: LLMGateway,
        store: Store,
        notifiers: list[Notifier],
        connectors: dict | None = None,
    ) -> None:
        self.gateway = gateway
        self.store = store
        self.notifiers = notifiers
        self.connectors = connectors or {}
        self.evidence_collector = EvidenceCollector(planner=InvestigationPlanner(gateway=gateway))
        self.repository = RepositoryDiscovery()
        self.fixer = FixGenerator(gateway=gateway)
        self.validation = ValidationRunner()

    async def handle(self, incident) -> InvestigationReport:
        """Run the full pipeline for a new incident, or short-circuit duplicates."""
        dedup = False
        if self.store.has_fingerprint(incident.fingerprint):
            stored = self.store.get_incident(incident.id)
            if stored is not None:
                dedup = True
                incident = self.store.upsert_incident(incident)
        if dedup:
            logger.info("skipping duplicate incident %s (fingerprint %s)", incident.id, incident.fingerprint)
            return InvestigationReport(incident=incident, status="duplicate")

        incident = self.store.upsert_incident(incident)
        report = InvestigationReport(incident=incident)

        try:
            report.evidence = await self.evidence_collector.collect(incident, self.connectors)
        except Exception:  # noqa: BLE001
            logger.exception("evidence collection failed for %s", incident.id)

        if report.evidence:
            location = await self.repository.resolve(incident, self.connectors.get("github_mcp"))
            report.root_cause = RootCause(
                location=location or CodeLocation(repository="unknown"),
                hypothesis="TODO: root-cause hypothesis from LLM",
                explanation="TODO: filled by root_cause_prompt",
                confidence=0.0,
            )
        else:
            report.status = "no_evidence"

        self.store.save_report(report)
        for notifier in self.notifiers:
            await notifier.send(report)
        return report