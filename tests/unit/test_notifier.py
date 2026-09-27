"""Channel notifiers deliver summaries and review requests without failing runs."""

from datetime import datetime

from patchthecode.config import MCPConnection
from patchthecode.domain import Severity
from patchthecode.domain.models import (
    CodeLocation,
    Evidence,
    FixProposal,
    Incident,
    IncidentSource,
    InvestigationReport,
    PullRequestResult,
    RootCause,
    ValidationResult,
)
from patchthecode.notifications.notifier import ChannelNotifier, LogNotifier, build_notifiers
from patchthecode.notifications.render import render_review_request, render_summary


class _FakeFacade:
    system = "slack"

    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []

    async def send_message(self, channel: str, text: str) -> bool:
        self.posts.append((channel, text))
        return True


class _BoomFacade:
    async def send_message(self, channel: str, text: str) -> bool:
        raise RuntimeError("channel offline")


class _FakeCommunication:
    def __init__(self) -> None:
        self.connection = MCPConnection(
            name="slack_mcp",
            kind="communication",
            system="slack",
            transport="stdio",
            command="npx",
        )

    async def list_tools(self) -> list[dict]:
        return [{"name": "chat_postMessage"}]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return {"content": "ok", "structured": {}}


class _FakeGit:
    def __init__(self) -> None:
        self.connection = MCPConnection(name="github_mcp", kind="git", transport="stdio", command="npx")

    async def list_tools(self) -> list[dict]:
        return [{"name": "get_content"}]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return {"content": "ok", "structured": {}}


def _incident() -> Incident:
    ts = datetime.utcnow()
    return Incident(
        id="n:1",
        fingerprint="fp",
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        occurrences=5,
        raw={},
    )


def _report() -> InvestigationReport:
    location = CodeLocation(repository="payments", branch="main", file_path="src/svc.py")
    return InvestigationReport(
        incident=_incident(),
        status="pr_opened",
        evidence=[
            Evidence(kind="query_logs", source_system="coralogix", content={"hits": 1}, confidence=0.6)
        ],
        root_cause=RootCause(
            location=location,
            explanation="log spike after deploy",
            hypothesis="unchecked null provider",
            confidence=0.9,
        ),
        fix=FixProposal(
            location=location,
            diff="--- a/src/svc.py\n+++ b/src/svc.py\n-return None\n+return valid",
            summary="guard the provider",
            related_files=["src/svc.py"],
        ),
        validation=ValidationResult(passed=True, checks=[{"name": "lint", "status": "passed"}]),
        pull_request=PullRequestResult(url="https://github.com/payments/payments/pull/9", number=9),
    )


def test_render_summary_covers_report_fields():
    text = render_summary(_report())
    assert "boom" in text
    assert "n:1" in text
    assert "fp" in text
    assert "unchecked null provider" in text
    assert "guard the provider" in text
    assert "https://github.com/payments/payments/pull/9" in text


def test_render_review_request_points_at_pr():
    text = render_review_request(_report())
    assert "Please review" in text
    assert "https://github.com/payments/payments/pull/9" in text


def test_render_review_request_points_at_branch_when_no_pr():
    report = _report()
    report.pull_request = None
    text = render_review_request(report)
    assert "branch `patchthecode/n:1`" in text


async def test_log_notifier_implements_the_notifier_contract():
    notifier = LogNotifier()
    await notifier.send(_report())
    await notifier.request_review(_report())


async def test_channel_notifier_posts_summary_and_review():
    facade = _FakeFacade()
    notifier = ChannelNotifier(facade)
    await notifier.send(_report())
    await notifier.request_review(_report())
    assert len(facade.posts) == 2
    assert facade.posts[0][0] == "#incidents"
    assert "boom" in facade.posts[0][1]
    assert "Please review" in facade.posts[1][1]


async def test_channel_notifier_swallows_facade_errors():
    notifier = ChannelNotifier(_BoomFacade())
    await notifier.send(_report())
    await notifier.request_review(_report())


def test_build_notifiers_creates_a_channel_per_communication_connector():
    notifiers = build_notifiers({"slack_mcp": _FakeCommunication(), "github_mcp": _FakeGit()})
    assert any(isinstance(n, LogNotifier) for n in notifiers)
    assert any(isinstance(n, ChannelNotifier) for n in notifiers)


def test_build_notifiers_skips_non_communication_connectors():
    notifiers = build_notifiers({"github_mcp": _FakeGit()})
    assert all(not isinstance(n, ChannelNotifier) for n in notifiers)