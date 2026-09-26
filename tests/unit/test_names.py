from patchthecode.config import MCPConnection
from patchthecode.integrations.appinsights import AppInsightsClient
from patchthecode.integrations.ci import CIClient
from patchthecode.integrations.coralogix import CoralogixClient
from patchthecode.integrations.factory import adapter_for
from patchthecode.integrations.github import GitHubClient
from patchthecode.integrations.gitlab import GitLabClient
from patchthecode.integrations.names import TOOL_SPECS, align_tools, report_for, tool_spec
from patchthecode.integrations.sentry import SentryClient


def test_align_picks_first_advertised_candidate():
    chosen = align_tools("sentry", ["list_issue_events", "search_foo"], None)
    assert chosen["list_events"] == "list_issue_events"
    assert chosen["search_issues"] == "search_issues"  # preferred default


def test_align_falls_back_to_preferred_when_not_advertised():
    chosen = align_tools("sentry", ["something_else"], None)
    assert chosen["list_events"] == "list_events"


def test_align_handles_empty_advertised() -> None:
    chosen = align_tools("github", [], None)
    assert chosen["get_content"] == "get_file_contents"


def test_align_overrides_win_over_advertised():
    chosen = align_tools(
        "sentry",
        ["list_issue_events", "search_issues"],
        {"list_events": "vendor_events_tool"},
    )
    assert chosen["list_events"] == "vendor_events_tool"


def test_align_is_case_insensitive_on_system():
    chosen = align_tools("GitLab", ["create_branch", "create_commit"], None)
    assert chosen["create_pr"] == "create_merge_request"


def test_report_flags_fallback_actions():
    report = report_for("sentry", ["list_issue_events"], None)
    by_action = {row["action"]: row for row in report["actions"]}
    assert by_action["list_events"]["status"] == "aligned"
    assert by_action["list_events"]["chosen"] == "list_issue_events"
    assert by_action["search_issues"]["status"] == "fallback"
    assert by_action["search_issues"]["candidates"] == ["search_issues", "list_issues", "get_list_issues"]
    assert report["total"] == 2


def test_report_marks_overrides():
    report = report_for("ci", ["create_check_run"], {"get_check_run": "vendor_poll"})
    row = {r["action"]: r for r in report["actions"]}["get_check_run"]
    assert row["override"] is True
    assert row["status"] == "fallback"


def test_unknown_system_has_empty_spec():
    assert tool_spec("jira") == {}


def test_every_client_action_has_a_spec_entry():
    pairs: list[tuple[str, type, list[str]]] = [
        ("github", GitHubClient, ["search_repositories", "get_content", "create_branch", "create_commit", "create_pr", "get_pr"]),
        ("gitlab", GitLabClient, ["search_repositories", "get_content", "create_branch", "create_commit", "create_pr", "get_pr"]),
        ("sentry", SentryClient, ["search_issues", "list_events"]),
        ("coralogix", CoralogixClient, ["query_logs", "list_deployments"]),
        ("appinsights", AppInsightsClient, ["query", "list_exceptions"]),
        ("ci", CIClient, ["create_check_run", "get_check_run"]),
    ]
    for system, _client_type, actions in pairs:
        spec = TOOL_SPECS[system]
        for action in actions:
            assert action in spec, f"{system} spec is missing action {action}"
            assert spec[action], f"{system} spec has no candidates for {action}"


def test_factory_clients_resolve_their_own_system():
    mcp = _AdvertisedMCP("github")
    assert adapter_for(_connection("srv", "git", "github"), mcp).system == "github"
    assert adapter_for(_connection("srv", "git", "gitlab"), mcp).system == "gitlab"
    assert adapter_for(_connection("srv", "observability", "sentry"), mcp).system == "sentry"
    assert adapter_for(_connection("srv", "observability", "appinsights"), mcp).system == "appinsights"
    assert adapter_for(_connection("srv", "observability", "coralogix"), mcp).system == "coralogix"
    assert adapter_for(_connection("srv", "ci"), mcp).system == "ci"


class _AdvertisedMCP:
    def __init__(self, system: str) -> None:
        self.system = system


def _connection(name: str, kind: str, system: str | None = None) -> MCPConnection:
    return MCPConnection(name=name, kind=kind, system=system, transport="stdio", command="npx")