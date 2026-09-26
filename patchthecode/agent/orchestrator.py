"""Agent core: orchestrates detect → investigate → remediate → notify.

This is a working skeleton. Each step delegates to a module; steps that are
not yet implemented raise clearly and leave the report partially filled so
the top-level loop stays honest about what happened.
"""

from __future__ import annotations

import logging

from patchthecode.domain.models import InvestigationReport
from patchthecode.investigation.analyzer import RootCauseAnalyzer
from patchthecode.investigation.evidence import EvidenceCollector
from patchthecode.investigation.planner import InvestigationPlanner
from patchthecode.llm.gateway import LLMGateway
from patchthecode.notifications.notifier import Notifier
from patchthecode.remediation.fixer import FixGenerator
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
        self.analyzer = RootCauseAnalyzer(gateway=gateway)
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
            report.root_cause = await self.analyzer.analyze(incident, report.evidence)
            location = report.root_cause.location
            if location.repository != "unknown" and location.file_path:
                logger.debug(
                    "resolved root cause for %s to %s@%s",
                    incident.id,
                    location.repository,
                    location.file_path,
                )
        else:
            report.status = "no_evidence"

        self.store.save_report(report)
        for notifier in self.notifiers:
            await notifier.send(report)
        return report