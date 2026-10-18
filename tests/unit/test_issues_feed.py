"""MCP issue feed: pull new issues from an observability facade as incidents."""

from datetime import datetime

from patchthecode.agent.issues import McpIssueFeed, default_action_for
from patchthecode.domain import Severity


class _FakeFacade:
    """A facade with the `execute`/`system` surface the feed uses."""

    def __init__(self, system: str, occurrences=None) -> None:
        self.system = system
        self._occurrences = occurrences or []
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, action: str, arguments: dict) -> list:
        self.calls.append((action, arguments))
        return self._occurrences


def _occurrence(
    title: str = "boom",
    message: str | None = None,
    exception_type: str | None = None,
    timestamp: datetime | None = None,
    system: str = "sentry",
):
    from patchthecode.detection.normalizer import NormalizedOccurrence

    return NormalizedOccurrence(
        system=system,
        kind="errors",
        severity=Severity.ERROR,
        title=title,
        description=None,
        exception_type=exception_type,
        message=message,
        stack_trace=None,
        timestamp=timestamp or datetime(2026, 10, 18, 12, 0, 0),
        service="payments-api",
        raw={},
    )


def test_default_action_for_picks_vendor_action():
    assert default_action_for(_FakeFacade("sentry")) == "search_issues"
    assert default_action_for(_FakeFacade("coralogix")) == "query_logs"
    assert default_action_for(_FakeFacade("appinsights")) == "list_exceptions"
    assert default_action_for(_FakeFacade("unknown-vendor")) == "search_issues"


async def test_fetch_groups_hits_by_fingerprint_into_one_incident():
    ts = datetime(2026, 10, 18, 12, 0, 0)
    facade = _FakeFacade(
        "sentry",
        occurrences=[
            _occurrence(title="NullPointerException", message="NPE", timestamp=ts),
            _occurrence(
                title="NullPointerException",
                message="NPE",
                timestamp=ts.replace(minute=1),
            ),
            _occurrence(title="connection reset", message="reset"),
        ],
    )
    feed = McpIssueFeed(facade, action="search_issues", arguments={"query": "is:unresolved"})

    incidents = await feed.fetch()

    assert len(incidents) == 2
    by_title = {i.title: i for i in incidents}
    assert by_title["NullPointerException"].occurrences == 2
    assert by_title["NullPointerException"].first_seen == ts
    assert by_title["NullPointerException"].last_seen == ts.replace(minute=1)
    assert by_title["connection reset"].occurrences == 1
    # fingerprints are stable and distinct per problem
    assert by_title["NullPointerException"].fingerprint != by_title["connection reset"].fingerprint
    assert facade.calls == [("search_issues", {"query": "is:unresolved"})]


async def test_acknowledge_skips_handed_out_incidents_on_next_poll():
    facade = _FakeFacade("sentry", occurrences=[_occurrence(title="boom")])
    feed = McpIssueFeed(facade)

    first = await feed.fetch()
    assert len(first) == 1
    await feed.acknowledge(first[0])

    second = await feed.fetch()
    assert second == []


async def test_unacknowledged_incident_is_refetched():
    facade = _FakeFacade("sentry", occurrences=[_occurrence(title="boom")])
    feed = McpIssueFeed(facade)

    first = await feed.fetch()
    second = await feed.fetch()
    assert len(first) == 1
    assert len(second) == 1
    # same fingerprint both times: the store will short-circuit the duplicate
    assert first[0].fingerprint == second[0].fingerprint


async def test_default_action_used_when_not_specified():
    facade = _FakeFacade("coralogix")
    feed = McpIssueFeed(facade, arguments={"query": "*"})
    await feed.fetch()
    assert facade.calls == [("query_logs", {"query": "*"})]
