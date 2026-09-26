"""Agent core: orchestrates detect → investigate → remediate → notify.

This is a working skeleton. Each step delegates to a module; steps that are
not yet implemented raise clearly and leave the report partially filled so
the top-level loop stays honest about what happened.
"""

from __future__ import annotations

import logging
from typing import cast

from patchthecode.config import MCPConnection
from patchthecode.domain.models import InvestigationReport, PullRequestData
from patchthecode.integrations.factory import adapter_for
from patchthecode.integrations.github import GitHubClient
from patchthecode.investigation.analyzer import RootCauseAnalyzer
from patchthecode.investigation.evidence import EvidenceCollector
from patchthecode.investigation.planner import InvestigationPlanner
from patchthecode.llm.gateway import LLMGateway
from patchthecode.notifications.notifier import Notifier
from patchthecode.remediation.fixer import FixGenerator
from patchthecode.security.approver import Approver, AutoApprover, LoggingApprover
from patchthecode.storage.store import Store
from patchthecode.validation.runner import ValidationRunner
from patchthecode.validation.static import StaticValidator

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
        auto_pr: bool = False,
        approver: Approver | None = None,
        static_validator: StaticValidator | None = None,
    ) -> None:
        self.gateway = gateway
        self.store = store
        self.notifiers = notifiers
        self.connectors = connectors or {}
        self.evidence_collector = EvidenceCollector(planner=InvestigationPlanner(gateway=gateway))
        self.analyzer = RootCauseAnalyzer(gateway=gateway)
        self.fixer = FixGenerator(gateway=gateway)
        self.validation = ValidationRunner(static=static_validator)
        self.github = self._find_git_connector()
        self.ci = self._find_ci_connector()
        self.approver = approver or (AutoApprover() if auto_pr else LoggingApprover())

    def _find_git_connector(self) -> GitHubClient | None:
        """Wrap the git-capable MCP connector using the adapter factory."""
        for client in self.connectors.values():
            connection = cast(MCPConnection | None, getattr(client, "connection", None))
            if connection is not None and connection.kind == "git":
                return adapter_for(connection, client)
        fallback = self.connectors.get("github_mcp")
        if fallback is None:
            return None
        fallback_connection = cast(MCPConnection | None, getattr(fallback, "connection", None))
        if fallback_connection is not None:
            return adapter_for(fallback_connection, fallback)
        return adapter_for(MCPConnection(name="github_mcp", kind="git"), fallback)

    def _find_ci_connector(self):
        """Wrap the CI-capable MCP connector via the adapter factory, if any."""
        for client in self.connectors.values():
            connection = cast(MCPConnection | None, getattr(client, "connection", None))
            if connection is not None and connection.kind == "ci":
                return adapter_for(connection, client)
        return None

    async def handle(self, incident) -> InvestigationReport:
        """Run the full pipeline for a new incident, or short-circuit duplicates."""
        if self.store.has_fingerprint(incident.fingerprint):
            known = self.store.known_fix(incident.fingerprint)
            if known is not None:
                fix, pr = known
                logger.info(
                    "recurring incident %s (fingerprint %s) already fixed by %s",
                    incident.id,
                    incident.fingerprint,
                    pr.url,
                )
                return InvestigationReport(
                    incident=incident,
                    status="already_fixed",
                    fix=fix,
                    pull_request=pr,
                )
            stored = self.store.get_incident(incident.id)
            if stored is not None:
                incident = self.store.upsert_incident(incident)
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
        if not report.fix.diff:
            report.status = "fix_unavailable"
            return
        report.status = "fix_proposed"
        report.validation = await self.validation.validate(report.fix, self.ci_connector())
        if not report.validation.passed:
            report.status = "validation_failed"
            return
        if self.github is None:
            report.status = "pr_write_failed"
            return
        if not await self.approver.approve(
            "open_pull_request",
            {
                "repository": root_cause.location.repository,
                "head_branch": self._pr_head_branch(report),
                "base_branch": root_cause.location.branch or "main",
                "files": report.fix.related_files,
            },
        ):
            report.status = "pr_pending_approval"
            return
        try:
            report.pull_request = await self.github.open_pull_request(self._build_pr_data(report))
        except Exception:  # noqa: BLE001 - a failed write stays a failed write, not a crash
            logger.exception("failed to open PR for %s", report.incident.id)
            report.status = "pr_write_failed"
            return
        report.status = "pr_opened"
        self.store.save_pull_request(report.incident.id, root_cause.location.repository, report.pull_request)

    async def poll_pull_requests(self, git_client=None) -> list[dict]:
        """Check open PRs and record merged/closed outcomes in the store.

        An accepted (merged) PR becomes the learned fix for the incident's
        fingerprint; a recurring incident then fast-paths to `already_fixed`.
        """
        git = git_client or self.github
        if git is None:
            return []
        updates: list[dict] = []
        for entry in self.store.open_pull_requests():
            try:
                state = await git.get_pull_request(entry["pr"], entry["repository"])
            except Exception:  # noqa: BLE001 - keep polling the rest
                logger.exception("failed to poll PR for %s", entry["incident_id"])
                continue
            if state == "open":
                continue
            self.store.mark_pull_request(entry["incident_id"], state)
            updates.append(
                {
                    "incident_id": entry["incident_id"],
                    "repository": entry["repository"],
                    "url": entry["pr"].url,
                    "state": state,
                }
            )
            logger.info("PR %s for incident %s is now %s", entry["pr"].url, entry["incident_id"], state)
        return updates

    def ci_connector(self):
        """Return the CI-MCP connector, if any, for validation checks."""
        return self.ci

    @staticmethod
    def _pr_head_branch(report: InvestigationReport) -> str:
        incident_id = report.incident.id.replace("/", "-")[-20:]
        return f"patchthecode/{incident_id}"

    @staticmethod
    def _build_pr_data(report: InvestigationReport) -> PullRequestData:
        if report.root_cause is None or report.fix is None:
            raise RuntimeError("cannot build PR data without a root cause and fix")
        location = report.root_cause.location
        fix = report.fix
        validation = report.validation
        evidence = "\n".join(
            f"- [{item.source_system}/{item.kind}] {item.confidence:.0%}"
            for item in report.evidence
        )
        description = (
            f"Auto-detected by PatchTheCode.\n\n"
            f"## Root cause\n{report.root_cause.hypothesis}\n\n"
            f"## Evidence\n{evidence}\n\n"
            f"## Fix\n{fix.summary}\n\n"
            f"## Validation\n"
            f"{'passed' if validation and validation.passed else 'pending'}\n\n"
            f"## Proposed diff\n```diff\n{fix.diff}\n```"
        )
        return PullRequestData(
            repository=location.repository,
            title=f"[PatchTheCode] {report.incident.title[:60]}",
            base_branch=location.branch or "main",
            head_branch=Agent._pr_head_branch(report),
            description=description,
            diff=fix.diff,
            files=fix.related_files,
        )