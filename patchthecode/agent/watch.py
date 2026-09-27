"""Long-running watch loop for autonomous operation.

Instead of a CLI call per incident, the loop polls a feed, drives each new
incident through the agent, and refreshes pull-request outcomes so the learning
signals (merged fixes, rejections) stay fresh between runs. A single bad
incident or flaky feed never stops the loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from patchthecode.agent.orchestrator import Agent
from patchthecode.agent.sources import IncidentFeed
from patchthecode.domain.models import InvestigationReport

logger = logging.getLogger(__name__)

ReportHook = Callable[[InvestigationReport], None]
CycleHook = Callable[[int], None]


class WatchLoop:
    """Poll a feed and investigate new incidents until told to stop."""

    def __init__(
        self,
        agent: Agent,
        feed: IncidentFeed,
        interval_seconds: float = 30.0,
        max_cycles: int | None = None,
        poll_pull_requests: bool = True,
        on_report: ReportHook | None = None,
        on_cycle: CycleHook | None = None,
        sleeper: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.agent = agent
        self.feed = feed
        self.interval_seconds = interval_seconds
        self.max_cycles = max_cycles
        self.poll_pull_requests = poll_pull_requests
        self.on_report = on_report
        self.on_cycle = on_cycle
        self._sleep = sleeper

    async def run(self) -> list[InvestigationReport]:
        """Run cycles until `max_cycles` is reached; returns every report."""
        reports: list[InvestigationReport] = []
        cycle = 0
        while self.max_cycles is None or cycle < self.max_cycles:
            cycle += 1
            if self.on_cycle is not None:
                self.on_cycle(cycle)
            reports.extend(await self.cycle())
            if self.max_cycles is not None and cycle >= self.max_cycles:
                break
            await self._sleep(self.interval_seconds)
        return reports

    async def cycle(self) -> list[InvestigationReport]:
        """One poll: investigate everything new, then refresh PR outcomes."""
        reports: list[InvestigationReport] = []
        try:
            incidents = await self.feed.fetch()
        except Exception:  # noqa: BLE001 - a flaky feed must not end the loop
            logger.exception("incident feed failed to list incidents")
            return reports
        for incident in incidents:
            try:
                report = await self.agent.handle(incident)
            except Exception:  # noqa: BLE001 - one bad incident must not end the loop
                logger.exception("investigation failed for %s; continuing", incident.id)
                continue
            reports.append(report)
            if self.on_report is not None:
                self.on_report(report)
            try:
                await self.feed.acknowledge(incident)
            except Exception:  # noqa: BLE001 - a re-delivered incident is deduped by the store
                logger.exception("could not acknowledge incident %s", incident.id)
        await self._refresh_pull_requests()
        return reports

    async def _refresh_pull_requests(self) -> None:
        if not self.poll_pull_requests:
            return
        try:
            updates = await self.agent.poll_pull_requests()
        except Exception:  # noqa: BLE001 - PR polling is best-effort
            logger.exception("pull-request polling failed; continuing")
            return
        for update in updates:
            logger.info(
                "pr %s -> %s (incident %s)", update["url"], update["state"], update["incident_id"]
            )
