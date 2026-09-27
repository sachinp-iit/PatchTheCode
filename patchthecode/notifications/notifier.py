"""Notify humans when an investigation finishes or a fix is ready.

Every notification goes through the MCP adapter layer like everything else:
a communication connector (kind=communication) is wrapped by the adapter
factory and each wrapped connector becomes a no-op-safe ChannelNotifier.
The console LogNotifier is always present so a run without chat connectors
still leaves a visible trace.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from patchthecode.domain.models import InvestigationReport
from patchthecode.integrations.factory import adapter_for
from patchthecode.notifications.render import render_review_request, render_summary

logger = logging.getLogger(__name__)


class Notifier(ABC):
    @abstractmethod
    async def send(self, report: InvestigationReport) -> None: ...

    @abstractmethod
    async def request_review(self, report: InvestigationReport) -> None: ...


class LogNotifier(Notifier):
    """Default notifier: log a summary line to the log stream."""

    async def send(self, report: InvestigationReport) -> None:
        logger.info("[notification] incident=%s status=%s", report.incident.id, report.status)

    async def request_review(self, report: InvestigationReport) -> None:
        logger.warning(
            "[review-request] incident=%s status=%s awaiting human approval",
            report.incident.id,
            report.status,
        )


class ChannelNotifier(Notifier):
    """Post report summaries and review requests to one chat facade."""

    def __init__(self, facade: Any, channel: str = "#incidents", label: str | None = None) -> None:
        self.facade = facade
        self.channel = channel
        self.label = label or getattr(facade, "system", "chat")

    async def send(self, report: InvestigationReport) -> None:
        try:
            await self.facade.send_message(self.channel, render_summary(report))
        except Exception:  # noqa: BLE001 - a failed notification must not fail the run
            logger.warning("failed to notify %s", self.label, exc_info=True)

    async def request_review(self, report: InvestigationReport) -> None:
        try:
            await self.facade.send_message(self.channel, render_review_request(report))
        except Exception:  # noqa: BLE001
            logger.warning("failed to request review via %s", self.label, exc_info=True)


def build_notifiers(connectors: dict[str, Any]) -> list[Notifier]:
    """LogNotifier always; a ChannelNotifier per communication connector.

    Connectors without a send_message surface (unknown chat vendors, raw MCP
    clients) are skipped rather than failing the build.
    """
    notifiers: list[Notifier] = [LogNotifier()]
    for client in connectors.values():
        connection = getattr(client, "connection", None)
        if connection is None or getattr(connection, "kind", "") != "communication":
            continue
        try:
            facade = adapter_for(connection, client)
        except Exception:  # noqa: BLE001 - a misconfigured connector just gets no channel
            logger.debug("could not build a channel for %r", getattr(connection, "name", "?"))
            continue
        if getattr(facade, "send_message", None) is not None:
            notifiers.append(ChannelNotifier(facade))
    return notifiers