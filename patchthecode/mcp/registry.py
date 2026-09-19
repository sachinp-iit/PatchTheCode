"""Registry of MCP connections grouped by capability kind.

Categorizes connectors so the agent can ask for one of each capability
(observability, git, ci, validation, communication) without knowing names.
"""

from __future__ import annotations

from collections import defaultdict

from patchthecode.config import MCPConnection
from patchthecode.mcp.client import MCPClient


class ConnectorRegistry:
    def __init__(self, connections: list[MCPConnection]) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._by_kind: dict[str, list[str]] = defaultdict(list)
        for conn in connections:
            self._clients[conn.name] = MCPClient(conn)
            self._by_kind[conn.kind].append(conn.name)

    def names(self) -> list[str]:
        return sorted(self._clients)

    def get(self, name: str) -> MCPClient:
        if name not in self._clients:
            raise KeyError(f"no connector named {name!r}")
        return self._clients[name]

    def all(self) -> list[MCPClient]:
        return list(self._clients.values())

    def by_kind(self, kind: str) -> list[MCPClient]:
        return [self._clients[name] for name in self._by_kind.get(kind, [])]

    def first_of_kind(self, kind: str) -> MCPClient | None:
        clients = self.by_kind(kind)
        return clients[0] if clients else None