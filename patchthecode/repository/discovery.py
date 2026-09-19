"""Resolve a service / incident to a repository location in source control."""

from __future__ import annotations

from typing import Any

from patchthecode.domain.models import CodeLocation, Incident


class RepositoryDiscovery:
    """Map an incident to a repo/branch/commit/file.

    TODO: implement against the git MCP connector:
        1. query observability for service name + deployment info
        2. search git MCP for repository by name/owner
        3. resolve branch + commit near the deployment time
        4. locate file/function from the root-cause hypothesis
    """

    async def resolve(self, incident: Incident, git_client: Any | None) -> CodeLocation | None:
        if git_client is None:
            return None
        service = (incident.raw.get("service")) if incident.raw else None
        if not service:
            return None
        return CodeLocation(repository=service, branch="main")