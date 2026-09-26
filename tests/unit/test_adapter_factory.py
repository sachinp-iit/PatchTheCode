from patchthecode.config import MCPConnection
from patchthecode.integrations.appinsights import AppInsightsClient
from patchthecode.integrations.ci import CIClient
from patchthecode.integrations.coralogix import CoralogixClient
from patchthecode.integrations.factory import adapter_for
from patchthecode.integrations.github import GitHubClient
from patchthecode.integrations.gitlab import GitLabClient
from patchthecode.integrations.sentry import SentryClient


def _connection(name: str, kind: str, system: str | None = None) -> MCPConnection:
    return MCPConnection(name=name, kind=kind, system=system, transport="stdio", command="npx")


def test_adapter_for_routes_git_by_system_hint():
    mcp = object()
    assert isinstance(adapter_for(_connection("core", "git", "gitlab"), mcp), GitLabClient)
    assert isinstance(adapter_for(_connection("core", "git", "github"), mcp), GitHubClient)
    assert isinstance(adapter_for(_connection("default_git", "git", "gitlab"), mcp), GitLabClient)


def test_adapter_for_defaults_git_to_github():
    assert isinstance(adapter_for(_connection("source", "git"), object()), GitHubClient)


def test_adapter_for_routes_observability_by_system_hint():
    mcp = object()
    assert isinstance(adapter_for(_connection("acme", "observability", "sentry"), mcp), SentryClient)
    assert isinstance(adapter_for(_connection("acme", "observability", "appinsights"), mcp), AppInsightsClient)
    assert isinstance(adapter_for(_connection("acme", "observability", "coralogix"), mcp), CoralogixClient)


def test_adapter_for_infers_sentry_from_name_when_system_missing():
    assert isinstance(adapter_for(_connection("sentry_prod", "observability"), object()), SentryClient)


def test_adapter_for_returns_ci_client_for_ci_kind():
    assert isinstance(adapter_for(_connection("pipeline", "ci"), object()), CIClient)


def test_adapter_for_returns_ci_client_for_validation_kind():
    assert isinstance(adapter_for(_connection("checks", "validation"), object()), CIClient)


def test_adapter_for_returns_raw_client_for_unknown_kinds():
    mcp = object()
    assert adapter_for(_connection("jira", "communication"), mcp) is mcp