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
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[dict]:
        return [{"name": t} for t in self.tools]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self.calls.append((name, arguments or {}))
        if name == "query_logs":
            return {"content": "NPE log entry", "structured": {"hits": 1}}
        if name == "get_content":
            return {"content": "class Svc { def process(self): return None }", "structured": {}}
        if name == "get_file_contents":
            return {"content": "return None", "structured": {"path": "src/svc.py"}}
        if name == "create_branch":
            return {"content": "branch created", "structured": {}}
        if name == "create_commit":
            return {"content": "commit created", "structured": {}}
        if name == "create_pull_request":
            return {"content": "PR created", "structured": {"url": "https://github.com/payments/payments/pull/1", "number": 1}}
        return {"content": f"result of {name}", "structured": {}}


async def test_agent_full_flow_blocks_pr_pending_approval(tmp_path):
    connectors = {
        "coralogix_mcp": _FakeMCP("coralogix_mcp", "observability", ["query_logs"]),
        "github_mcp": _FakeMCP("github_mcp", "git", ["get_content", "get_file_contents", "create_branch", "create_commit", "create_pull_request"]),
    }
    store = Store(tmp_path / "test.db")
    agent = Agent(gateway=_ScriptedGateway(), store=store, notifiers=[], connectors=connectors)
    report = await agent.handle(_incident(incident_id="full:1", fingerprint="fp-full"))
    assert report.status == "pr_pending_approval"
    assert report.fix is not None
    assert report.fix.diff.startswith("--- a/")
    assert report.fix.root_cause is not None
    assert report.fix.root_cause.location.repository == "payments"
    assert report.root_cause is not None
    assert report.root_cause.location.file_path == "src/svc.py"
    assert report.pull_request is None


async def test_agent_full_flow_opens_pr_when_auto_approved(tmp_path):
    github = _FakeMCP(
        "github_mcp",
        "git",
        ["get_file_contents", "create_branch", "create_commit", "create_pull_request"],
    )
    connectors = {
        "coralogix_mcp": _FakeMCP("coralogix_mcp", "observability", ["query_logs"]),
        "github_mcp": github,
    }
    store = Store(tmp_path / "test.db")
    agent = Agent(
        gateway=_ScriptedGateway(),
        store=store,
        notifiers=[],
        connectors=connectors,
        auto_pr=True,
    )
    report = await agent.handle(_incident(incident_id="pr:1", fingerprint="fp-pr"))
    assert report.status == "pr_opened"
    assert report.pull_request is not None
    assert report.pull_request.url == "https://github.com/payments/payments/pull/1"
    assert report.pull_request.number == 1

    tool_names = [name for name, _ in github.calls]
    assert "create_branch" in tool_names
    assert "create_commit" in tool_names
    assert "create_pull_request" in tool_names

    commit_args = next(arguments for name, arguments in github.calls if name == "create_commit")
    assert commit_args["branch"] == "patchthecode/pr:1"
    assert commit_args["files"] == [{"path": "src/svc.py", "content": "return valid"}]

    pr_args = next(arguments for name, arguments in github.calls if name == "create_pull_request")
    assert pr_args["head"] == "patchthecode/pr:1"
    assert pr_args["base"] == "main"
    assert "## Root cause" in pr_args["body"]


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