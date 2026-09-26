"""Adapters are chosen by *kind* (+ system hint), never by connector name.

This is the seam that makes PatchTheCode vendor-neutral: point it at a GitLab,
Sentry, or App Insights MCP server and it picks the right client without the
agent core knowing anything about the vendor.
"""

from __future__ import annotations

from typing import Any

from patchthecode.config import MCPConnection
from patchthecode.integrations.appinsights import AppInsightsClient
from patchthecode.integrations.ci import CIClient
from patchthecode.integrations.coralogix import CoralogixClient
from patchthecode.integrations.github import GitHubClient
from patchthecode.integrations.gitlab import GitLabClient
from patchthecode.integrations.sentry import SentryClient
from patchthecode.mcp.client import MCPClient


def hint_for(connection: MCPConnection) -> str:
    """Resolve the vendor hint: explicit `system` field beats name guessing."""
    if connection.system:
        return connection.system.lower()
    return connection.name.lower()


def adapter_for(connection: MCPConnection, mcp_client: MCPClient) -> Any:
    """Build the client facade matching a connector's kind and system hint."""
    kind = connection.kind.lower()
    hint = hint_for(connection)
    if kind == "git":
        if "gitlab" in hint:
            return GitLabClient(mcp_client)
        return GitHubClient(mcp_client)
    if kind in {"observability", "logs"}:
        if "sentry" in hint or "sentry" in connection.name.lower():
            return SentryClient(mcp_client)
        if "appinsights" in hint or "appinsights" in connection.name.lower():
            return AppInsightsClient(mcp_client)
        return CoralogixClient(mcp_client)
    if kind in {"ci", "validation"}:
        return CIClient(mcp_client)
    return mcp_client  # no dedicated facade during the skeleton phase