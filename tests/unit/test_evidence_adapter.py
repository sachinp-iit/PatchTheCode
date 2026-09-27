"""Evidence collection routes through adapted facades: normalize and dedupe at the source."""

from datetime import datetime

import pytest

from patchthecode.config import MCPConnection
from patchthecode.domain import Severity
from patchthecode.domain.models import Incident, IncidentSource
from patchthecode.integrations.errors import UnknownActionError
from patchthecode.integrations.factory import adapter_for
from patchthecode.investigation.evidence import EvidenceCollector
from patchthecode.investigation.planner import EvidencePlanItem


class _RawConnector:
    """A plain MCP client with the surface `adapter_for` needs."""

    def __init__(self, kind: str, name: str, tools: list[str], handler=None) -> None:
        self.connection = MCPConnection(name=name, kind=kind, transport="stdio", command="npx")
        self.tools = tools
        self.handler = handler

    async def list_tools(self) -> list[dict]:
        return [{"name": t} for t in self.tools]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        if self.handler is not None:
            return await self.handler(name, arguments or {})
        return {"content": f"result of {name}", "structured": {}}


class _Plan:
    def __init__(self, steps: list[EvidencePlanItem]) -> None:
        self._steps = steps

    async def plan(self, incident: Incident, connectors: dict) -> list[EvidencePlanItem]:
        return self._steps


def _incident() -> Incident:
    ts = datetime.utcnow()
    return Incident(
        id="t:1",
        fingerprint="fp",
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={"service": "payments-api"},
    )


async def _logs_handler(name: str, arguments: dict) -> dict:
    return {
        "content": "ok",
        "structured": {
            "hits": [
                {"text": "NullPointerException", "applicationName": "payments-api", "severity": 5},
                {"text": "NullPointerException", "applicationName": "payments-api", "severity": 5},
                {"text": "connection reset", "applicationName": "payments-api", "severity": 4},
            ]
        },
    }


def _query_logs_step(**arguments: object) -> EvidencePlanItem:
    return EvidencePlanItem(
        connector="coralogix_mcp",
        tool="query_logs",
        arguments=arguments or {"query": "*", "time_range": {}},
        purpose="logs",
    )


async def test_coralogix_execute_normalizes_hits():
    connector = _RawConnector("observability", "coralogix_mcp", ["query_logs"], handler=_logs_handler)
    facade = adapter_for(connector.connection, connector)
    occurrences = await facade.execute("query_logs", {"query": "*", "time_range": {}})
    assert len(occurrences) == 3
    assert occurrences[0].system == "coralogix"
    assert occurrences[0].service == "payments-api"
    with pytest.raises(UnknownActionError):
        await facade.execute("list_deployments", {})


async def test_collector_normalizes_and_dedupes_occurrences():
    connector = _RawConnector("observability", "coralogix_mcp", ["query_logs"], handler=_logs_handler)
    collector = EvidenceCollector(planner=_Plan([_query_logs_step()]))
    evidence = await collector.collect(_incident(), {"coralogix_mcp": connector})
    assert len(evidence) == 1
    entry = evidence[0]
    assert entry.kind == "query_logs"
    assert entry.source_system == "coralogix_mcp"
    assert entry.content["occurrence_count"] == 3
    assert entry.content["unique_fingerprints"] == 2
    fingerprints = {o["fingerprint"] for o in entry.content["occurrences"]}
    assert len(fingerprints) == 2


async def test_collector_falls_back_to_raw_for_git_step():
    connector = _RawConnector("git", "github_mcp", ["get_content"])
    step = EvidencePlanItem(connector="github_mcp", tool="get_content", arguments={"path": "a.py"}, purpose="source")
    collector = EvidenceCollector(planner=_Plan([step]))
    evidence = await collector.collect(_incident(), {"github_mcp": connector})
    assert len(evidence) == 1
    assert "result of get_content" in str(evidence[0].content)


async def test_collector_keeps_unrecognizable_connectors_raw_without_crashing():
    connector = _RawConnector("communication", "slack_mcp", ["post"])
    step = EvidencePlanItem(connector="slack_mcp", tool="post", arguments={}, purpose="x")
    collector = EvidenceCollector(planner=_Plan([step]))
    evidence = await collector.collect(_incident(), {"slack_mcp": connector})
    assert len(evidence) == 1
    assert "result of post" in str(evidence[0].content)


async def test_collector_redacts_tokens_in_occurrence_summary():
    async def handler(name: str, arguments: dict) -> dict:
        return {
            "content": "ok",
            "structured": {
                "hits": [{"text": "auth failed token=abc123", "applicationName": "svc", "severity": 5}]
            },
        }

    connector = _RawConnector("observability", "coralogix_mcp", ["query_logs"], handler=handler)
    collector = EvidenceCollector(planner=_Plan([_query_logs_step()]))
    evidence = await collector.collect(_incident(), {"coralogix_mcp": connector})
    message = evidence[0].content["occurrences"][0]["message"]
    assert message == "auth failed [REDACTED]"


async def test_sentry_execute_routes_search_issues_and_list_events():
    async def handler(name: str, arguments: dict) -> dict:
        if name == "search_issues":
            return {"content": "ok", "structured": {"issues": [{"title": "boom", "level": "fatal"}]}}
        return {"content": "ok", "structured": {"events": [{"title": "event boom", "level": "error"}]}}

    connector = _RawConnector("observability", "sentry_mcp", ["search_issues", "list_issue_events"], handler=handler)
    facade = adapter_for(connector.connection, connector)
    issues = await facade.execute("search_issues", {"query": "unresolved"})
    assert issues[0].system == "sentry"
    events = await facade.execute("list_events", {"issue_id": "1"})
    assert events[0].title == "event boom"


async def test_appinsights_execute_routes_query():
    async def handler(name: str, arguments: dict) -> dict:
        return {"content": "ok", "structured": {"rows": [{"message": "trace", "severityLevel": 4}]}}

    connector = _RawConnector("observability", "appinsights_mcp", ["run_query"], handler=handler)
    facade = adapter_for(connector.connection, connector)
    rows = await facade.execute("query", {"query": "traces | take 1"})
    assert rows[0].system == "appinsights"