"""Vendor MCP integrations.

Each subpackage wraps one MCP connector and hides vendor specifics from the
agent core. Add `jira/`, `bitbucket/`, `ci/` here as needed. Adapters are
selected by kind via `adapter_for`.
"""

from patchthecode.integrations.appinsights import AppInsightsClient
from patchthecode.integrations.coralogix import CoralogixClient
from patchthecode.integrations.factory import adapter_for
from patchthecode.integrations.github import GitHubClient
from patchthecode.integrations.gitlab import GitLabClient
from patchthecode.integrations.sentry import SentryClient

__all__ = [
    "AppInsightsClient",
    "CoralogixClient",
    "GitHubClient",
    "GitLabClient",
    "SentryClient",
    "adapter_for",
]