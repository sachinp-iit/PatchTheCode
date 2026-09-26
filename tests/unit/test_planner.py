from datetime import datetime

from patchthecode.domain import Severity
from patchthecode.domain.models import Incident, IncidentSource
from patchthecode.investigation.evidence import EvidenceCollector
from patchthecode.investigation.planner import EvidencePlanItem, InvestigationPlanner


class _FakeConnector:
    connection = type("Conn", (), {"kind": "observability"})()

    def __init__(self, tools: list[str] | None = None) -> None:
        self._tools = tools or []

    async def list_tools(self) -> list[dict]:
        return [{"name": t} for t in self._tools]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return {"content": f"result of {name}", "structured": {}}


class _FakeGateway:
    def __init__(self, steps: list[dict] | None = None, raise_error: bool = False) -> None:
        self.steps = steps or []
        self.raise_error = raise_error

    async def complete_json(self, task: str, messages: list[dict[str, str]]) -> dict:
        if self.raise_error:
            raise RuntimeError("model down")
        return {"steps": self.steps}


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


async def test_fallback_plan_used_when_no_gateway():
    planner = InvestigationPlanner(gateway=None)
    items = await planner.plan(_incident(), {"coralogix_mcp": object()})
    assert isinstance(items, list)
    assert all(isinstance(i, EvidencePlanItem) for i in items)
    assert items[0].connector == "coralogix_mcp"
    assert items[0].tool == "query_logs"


async def test_fallback_plan_used_when_gateway_fails():
    planner = InvestigationPlanner(gateway=_FakeGateway(raise_error=True))
    items = await planner.plan(_incident(), {})
    assert items[-1].connector == "github_mcp"


async def test_llm_plan_parsed_in_order():
    gateway = _FakeGateway(steps=[{"connector": "a", "tool": "t1", "arguments": {"q": "x"}, "purpose": "p"}])
    planner = InvestigationPlanner(gateway=gateway)
    items = await planner.plan(_incident(), {"a": _FakeConnector(["t1"])})
    assert items == [EvidencePlanItem(connector="a", tool="t1", arguments={"q": "x"}, purpose="p")]


async def test_llm_plan_drops_unknown_connectors():
    gateway = _FakeGateway(
        steps=[
            {"connector": "known", "tool": "t1", "arguments": {}, "purpose": "ok"},
            {"connector": "ghost", "tool": "t1", "arguments": {}, "purpose": "skip"},
        ]
    )
    planner = InvestigationPlanner(gateway=gateway)
    items = await planner.plan(_incident(), {"known": _FakeConnector(["t1"])})
    assert len(items) == 1
    assert items[0].connector == "known"


async def test_llm_plan_drops_unknown_tools():
    gateway = _FakeGateway(steps=[{"connector": "a", "tool": "nope", "arguments": {}, "purpose": "skip"}])
    planner = InvestigationPlanner(gateway=gateway)
    items = await planner.plan(_incident(), {"a": _FakeConnector(["t1", "t2"])})
    assert items == []


async def test_llm_invalid_schema_falls_back():
    gateway = _FakeGateway(steps=[{"connector": "a"}])  # missing required "tool"
    planner = InvestigationPlanner(gateway=gateway)
    items = await planner.plan(_incident(), {})
    assert items[-1].tool == "search_repository"


async def test_evidence_collector_executes_fallback_plan():
    connectors = {
        "coralogix_mcp": _FakeConnector(),
        "github_mcp": _FakeConnector(),
    }
    collector = EvidenceCollector(planner=InvestigationPlanner(gateway=None))
    evidence = await collector.collect(_incident(), connectors)
    kinds = {e.kind for e in evidence}
    assert "query_logs" in kinds
    assert "search_repository" in kinds


async def test_evidence_collector_executes_llm_plan():
    gateway = _FakeGateway(steps=[{"connector": "github_mcp", "tool": "get_content", "arguments": {"path": "a.py"}, "purpose": "source"}])
    connectors = {"github_mcp": _FakeConnector(["get_content"])}
    collector = EvidenceCollector(planner=InvestigationPlanner(gateway=gateway))
    evidence = await collector.collect(_incident(), connectors)
    assert len(evidence) == 1
    assert evidence[0].kind == "get_content"
    assert "result of get_content" in str(evidence[0].content)