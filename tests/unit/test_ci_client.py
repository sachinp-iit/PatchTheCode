from patchthecode.config import MCPConnection
from patchthecode.integrations.ci import CIClient


class _FakeMCP:
    def __init__(self) -> None:
        self.connection = MCPConnection(name="ci_vendor", kind="ci", transport="stdio", command="npx")
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[dict]:
        return [{"name": "create_check_run"}, {"name": "get_check_run"}]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self.calls.append((name, arguments or {}))
        if name == "create_check_run":
            return {"content": "ok", "structured": {"check_ref": "chk-9"}}
        if name == "get_check_run":
            return {"content": "done", "structured": {"checks": [{"name": "ci/unit", "status": "passed"}]}}
        return {"content": "unknown", "structured": {}}


async def test_ci_client_submits_and_polls():
    mcp = _FakeMCP()
    client = CIClient(mcp)
    ref = await client.submit_check("acme/pay", "--- a/x\n+++ b/x\n", branch="patchthecode/1")
    assert ref == "chk-9"
    assert mcp.calls[0] == (
        "create_check_run",
        {"repository": "acme/pay", "diff": "--- a/x\n+++ b/x\n", "branch": "patchthecode/1"},
    )

    checks = await client.poll_checks(ref)
    assert checks == [{"name": "ci/unit", "status": "passed"}]
    assert mcp.calls[1] == ("get_check_run", {"check_ref": "chk-9"})


async def test_ci_client_defaults_poll_payload_rows():
    mcp = _FakeMCP()

    async def _poll(name: str, arguments: dict | None = None) -> dict:
        return {"content": "done", "structured": {"status": "failed", "name": "ci/full"}}

    mcp.call_tool = _poll  # type: ignore[method-assign]
    client = CIClient(mcp)
    checks = await client.poll_checks("chk-9")
    assert checks == [{"name": "ci/full", "status": "failed"}]