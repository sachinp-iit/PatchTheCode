from patchthecode.config import MCPConnection
from patchthecode.mcp.registry import ConnectorRegistry


def test_registry_groups_by_kind():
    conns = [
        MCPConnection(name="coralogix_mcp", kind="observability", transport="stdio", command="coralogix-mcp"),
        MCPConnection(name="github_mcp", kind="git", transport="stdio", command="github-mcp"),
        MCPConnection(name="checks_mcp", kind="ci", transport="stdio", command="ci-mcp"),
    ]
    registry = ConnectorRegistry(conns)
    assert registry.names() == ["checks_mcp", "coralogix_mcp", "github_mcp"]
    assert [c.connection.name for c in registry.by_kind("git")] == ["github_mcp"]
    assert registry.first_of_kind("observability") is not None
    assert registry.first_of_kind("communication") is None


def test_registry_missing_name_raises():
    registry = ConnectorRegistry([])
    try:
        registry.get("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError")