"""Vendor MCP integrations.

Each subpackage wraps one MCP connector and hides vendor specifics from the
agent core. Add `application_insights/`, `sentry/`, `gitlab/`, `bitbucket/`,
`jira/`, `ci/` here as needed.
"""

from patchthecode.integrations.coralogix import CoralogixClient
from patchthecode.integrations.github import GitHubClient

__all__ = ["CoralogixClient", "GitHubClient"]