from datetime import datetime

import pytest

from patchthecode.agent.orchestrator import Agent
from patchthecode.config import MCPConnection
from patchthecode.domain import Severity
from patchthecode.domain.models import Incident, IncidentSource
from patchthecode.llm.gateway import LLMGateway
from patchthecode.notifications.notifier import LogNotifier
from patchthecode.storage.store import Store


@pytest.fixture()
def agent(tmp_path):
    gateway = LLMGateway([], timeout_seconds=5)
    store = Store(tmp_path / "test.db")
    return Agent(gateway=gateway, store=store, notifiers=[LogNotifier()])


def _incident(incident_id: str = "t:x:1", fingerprint: str = "fp-1") -> Incident:
    ts = datetime.utcnow()
    return Incident(
        id=incident_id,
        fingerprint=fingerprint,
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={"service": "svc"},
    )


class _ScriptedGateway:
    """Emulates the three LLM steps of the pipeline in order."""

    async def complete_json(self, task: str, messages: list[dict[str, str]]) -> dict:
        user = messages[-1]["content"] if messages else ""
        if "AVAILABLE MCP CONNECTORS" in user:
            return {
                "steps": [
                    {"connector": "coralogix_mcp", "tool": "query_logs", "arguments": {"q": "*"}, "purpose": "logs"},
                    {"connector": "github_mcp", "tool": "get_content", "arguments": {"path": "src/svc.py"}, "purpose": "source"},
                ]
            }
        if "Determine the root cause" in user:
            return {
                "hypothesis": "unchecked null provider",
                "confidence": 0.9,
                "repository": "payments",
                "file_path": "src/svc.py",
                "function": "process",
                "explanation": "log spike after deploy",
                "evidence_refs": ["query_logs"],
            }
        if "Generate a minimal fix" in user:
            return {
                "diff": "--- a/src/svc.py\n+++ b/src/svc.py\n@@ -1 +1 @@\n-return None\n+return valid",
                "summary": "guard the provider",
                "files": ["src/svc.py"],
            }
        raise AssertionError(f"unexpected gateway call: task={task} user={user[:80]!r}")


class _FakeMCP:
    def __init__(self, name: str, kind: str, tools: list[str]) -> None:
        self.connection = MCPConnection(name=name, kind=kind, transport="stdio", command="npx")
        self.tools = tools

    async def list_tools(self) -> list[dict]:
        return [{"name": t} for t in self.tools]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        if name == "query_logs":
            return {"content": "NPE log entry", "structured": {"hits": 1}}
        if name == "get_content":
            return {"content": "class Svc { def process(self): return None }", "structured": {}}
        return {"content": f"result of {name}", "structured": {}}


async def test_agent_full_flow_generates_fix(tmp_path):
    connectors = {
        "coralogix_mcp": _FakeMCP("coralogix_mcp", "observability", ["query_logs"]),
        "github_mcp": _FakeMCP("github_mcp", "git", ["get_content"]),
    }
    store = Store(tmp_path / "test.db")
    agent = Agent(gateway=_ScriptedGateway(), store=store, notifiers=[], connectors=connectors)
    report = await agent.handle(_incident(incident_id="full:1", fingerprint="fp-full"))
    assert report.status == "fix_proposed"
    assert report.fix is not None
    assert report.fix.diff.startswith("--- a/")
    assert report.fix.root_cause is not None
    assert report.fix.root_cause.location.repository == "payments"
    assert report.root_cause is not None
    assert report.root_cause.location.file_path == "src/svc.py"


async def test_agent_fix_unavailable_without_git_connector(tmp_path):
    connectors = {
        "coralogix_mcp": _FakeMCP("coralogix_mcp", "observability", ["query_logs"]),
    }
    store = Store(tmp_path / "test.db")
    agent = Agent(gateway=_ScriptedGateway(), store=store, notifiers=[], connectors=connectors)
    report = await agent.handle(_incident(incident_id="nogit:1", fingerprint="fp-nogit"))
    assert report.status == "fix_unavailable"
    assert report.fix is not None
    assert report.fix.summary == "Code snippet unavailable; fix not generated"


async def test_agent_short_circuits_duplicates(agent):
    first = await agent.handle(_incident())
    assert first.status == "no_evidence"
    second = await agent.handle(_incident())
    assert second.status == "duplicate"


async def test_agent_upserts_occurrence_counts(agent):
    one = _incident()
    agent.store.upsert_incident(one)
    repeat = _incident()
    repeat.occurrences = 5
    merged = agent.store.upsert_incident(repeat)
    assert merged.occurrences == 6