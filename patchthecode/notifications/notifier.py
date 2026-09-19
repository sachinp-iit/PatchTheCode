"""Notify humans when an investigation finishes or a fix is ready."""

from __future__ import annotations

from abc import ABC, abstractmethod

from patchthecode.domain.models import InvestigationReport


class Notifier(ABC):
    @abstractmethod
    async def send(self, report: InvestigationReport) -> None: ...


class LogNotifier(Notifier):
    """Default notifier: print a summary to the log stream."""

    async def send(self, report: InvestigationReport) -> None:
        print(f"[notification] incident={report.incident.id} status={report.status}")  # noqa: T201


class SlackNotifier(Notifier):
    """POST the report summary to a Slack webhook (adapt for Teams later)."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send(self, report: InvestigationReport) -> None:
        # TODO: build a real Slack message block (text + PR link); use httpx.
        raise NotImplementedError("SlackNotifier.send is not implemented yet.")


def build_notifiers(slack_webhook_url: str | None = None, teams_webhook_url: str | None = None) -> list[Notifier]:
    notifiers: list[Notifier] = [LogNotifier()]
    if slack_webhook_url:
        notifiers.append(SlackNotifier(slack_webhook_url))
    if teams_webhook_url:
        raise NotImplementedError("Teams notifier is not implemented yet.")
    return notifiers