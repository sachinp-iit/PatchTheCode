"""Clients resolve tool names against the server's advertised tools at runtime."""

from collections.abc import Awaitable, Callable
from datetime import datetime

from patchthecode.domain.models import CodeLocation, PullRequestData
from patchthecode.integrations.appinsights import AppInsightsClient
from patchthecode.integrations.ci import CIClient
from patchthecode.integrations.coralogix import CoralogixClient
from patchthecode.integrations.github import GitHubClient
from patchthecode.integrations.sentry import SentryClient

CallHandler = Callable[[str, dict | None], Awaitable[dict]]


class _AdvertisedMCP:
    """A fake MCP server advertising a vendor's tool names."""

    def __init__(self, advertised: list[str], handler: CallHandler | None = None) -> None:
        self.advertised = advertised
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[dict]:
        return [{"name": name} for name in self.advertised]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self.calls.append((name, arguments or {}))
        if self.handler is not None:
            return await self.handler(name, arguments)
        return {"content": "ok", "structured": {}}


async def test_sentry_aligns_to_list_issue_events():
    mcp = _AdvertisedMCP(["list_issue_events", "search_issues"], handler=_sentry_events_call)
    client = SentryClient(mcp)
    events = await client.list_events("issue-1")
    assert mcp.calls[0][0] == "list_issue_events"
    assert events[0].title == "TypeError boom"


async def _sentry_events_call(name: str, arguments: dict | None = None) -> dict:
    return {
        "content": "ok",
        "structured": {
            "events": [
                {
                    "id": "e1",
                    "title": "TypeError boom",
                    "level": "error",
                    "dateCreated": datetime.utcnow().isoformat(),
                }
            ]
        },
    }


async def test_ci_aligns_to_vendor_poll_tool():
    mcp = _AdvertisedMCP(["start_check", "poll_check"], handler=_ci_call)
    client = CIClient(mcp)
    ref = await client.submit_check("acme/pay", "--- a\n+++ b\n")
    assert ref == "chk-9"
    checks = await client.poll_checks(ref)
    assert checks == [{"name": "ci/vendor", "status": "passed"}]


async def _ci_call(name: str, arguments: dict | None = None) -> dict:
    if name == "start_check":
        return {"content": "ok", "structured": {"check_ref": "chk-9"}}
    if name == "poll_check":
        return {"content": "done", "structured": {"checks": [{"name": "ci/vendor", "status": "passed"}]}}
    return {"content": "unknown", "structured": {}}


async def test_coralogix_aligns_to_search_logs():
    mcp = _AdvertisedMCP(["search_logs", "list_deployments"], handler=_coralogix_call)
    client = CoralogixClient(mcp)
    hits = await client.query_logs("*", {})
    assert mcp.calls[0][0] == "search_logs"
    assert hits[0].service == "payments-api"


async def _coralogix_call(name: str, arguments: dict | None = None) -> dict:
    if name == "search_logs":
        return {"content": "ok", "structured": {"hits": [{"text": "NPE", "applicationName": "payments-api"}]}}
    return {"content": "ok", "structured": {}}


async def test_appinsights_aligns_to_run_query():
    mcp = _AdvertisedMCP(["run_query", "list_exceptions"], handler=_appinsights_call)
    client = AppInsightsClient(mcp)
    rows = await client.query("traces | take 5")
    assert mcp.calls[0][0] == "run_query"
    assert rows[0].system == "appinsights"


async def _appinsights_call(name: str, arguments: dict | None = None) -> dict:
    if name == "run_query":
        return {"content": "ok", "structured": {"rows": [{"message": "boom", "severityLevel": 5}]}}
    return {"content": "ok", "structured": {}}


async def test_github_resolves_alternate_content_tool():
    mcp = _AdvertisedMCP(
        ["get_content", "create_branch", "create_commit", "create_pull_request", "get_pull_request"],
        handler=_github_call,
    )
    client = GitHubClient(mcp)
    source = await client.resolve_file(CodeLocation(repository="acme/pay", file_path="src/svc.py"))
    assert source == "return None"
    assert mcp.calls[0][0] == "get_content"


async def _github_call(name: str, arguments: dict | None = None) -> dict:
    if name in {"get_content", "get_file_contents"}:
        return {"content": "return None", "structured": {}}
    return {"content": "ok", "structured": {}}


async def test_explicit_tool_names_override_win():
    mcp = _AdvertisedMCP(["search_logs", "list_deployments"])
    client = CoralogixClient(mcp, tool_names={"query_logs": "vendor_query"})
    await client.query_logs("*", {})
    assert mcp.calls[0][0] == "vendor_query"


async def test_github_pr_open_uses_aligned_names():
    mcp = _AdvertisedMCP(
        ["get_file_contents", "create_branch", "create_commit", "create_pull_request", "get_pull_request"],
        handler=_github_call,
    )
    data = PullRequestData(
        repository="acme/pay",
        title="fix",
        description="body",
        head_branch="patchthecode/1",
        base_branch="main",
        files=["src/svc.py"],
        diff="--- a/src/svc.py\n+++ b/src/svc.py\n@@ -1 +1 @@\n-return None\n+return valid",
    )
    client = GitHubClient(mcp)
    await client.open_pull_request(data)
    used = [name for name, _ in mcp.calls]
    assert used == ["get_file_contents", "create_branch", "create_commit", "create_pull_request"]


async def test_gitlab_client_uses_gitlab_system():
    from patchthecode.integrations.gitlab import GitLabClient

    mcp = _AdvertisedMCP(["create_branch", "create_commit", "create_merge_request", "get_file_contents"])
    client = GitLabClient(mcp)
    assert client._system == "gitlab"