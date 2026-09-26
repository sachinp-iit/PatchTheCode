"""Agent core: orchestrates detect → investigate → remediate → notify.

This is a working skeleton. Each step delegates to a module; steps that are
not yet implemented raise clearly and leave the report partially filled so
the top-level loop stays honest about what happened.
"""

from __future__ import annotations

import logging

from patchthecode.domain.models import InvestigationReport
from patchthecode.integrations.github import GitHubClient
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
        self.github = self._find_git_connector()

    def _find_git_connector(self) -> GitHubClient | None:
        """Wrap the git-capable MCP connector, preferring kind over name."""
        for client in self.connectors.values():
            if getattr(getattr(client, "connection", None), "kind", None) == "git":
                return GitHubClient(client)
        fallback = self.connectors.get("github_mcp")
        return GitHubClient(fallback) if fallback is not None else None

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
            await self._propose_fix(report)
        else:
            report.status = "no_evidence"

        self.store.save_report(report)
        for notifier in self.notifiers:
            await notifier.send(report)
        return report

    async def _propose_fix(self, report: InvestigationReport) -> None:
        """Generate a candidate fix when the root cause resolves to a file."""
        root_cause = report.root_cause
        if root_cause is None or not root_cause.location.file_path:
            return
        snippet: str | None = None
        if self.github is not None:
            try:
                snippet = await self.github.resolve_file(root_cause.location)
            except Exception:  # noqa: BLE001 - a read failure just means no fix this round
                logger.warning("could not fetch source for %s", root_cause.location.file_path, exc_info=True)
        report.fix = await self.fixer.propose(root_cause.location, snippet or "", root_cause)
        report.status = "fix_proposed" if report.fix.diff else "fix_unavailable"