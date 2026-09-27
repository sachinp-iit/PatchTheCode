"""Slack and Teams facades post messages through a communication MCP connector."""

from patchthecode.integrations.slack import SlackClient
from patchthecode.integrations.teams import TeamsClient


class _FakeChannel:
    def __init__(self, tools: list[str]) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[dict]:
        return [{"name": t} for t in self.tools]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self.calls.append((name, arguments or {}))
        return {"content": f"result of {name}", "structured": {}}


async def test_slack_send_message_uses_advertised_tool():
    fake = _FakeChannel(["chat_postMessage"])
    client = SlackClient(fake)
    assert await client.send_message("#incidents", "hello") is True
    name, arguments = fake.calls[0]
    assert name == "chat_postMessage"
    assert arguments == {"channel": "#incidents", "text": "hello"}


async def test_slack_send_message_defaults_channel():
    fake = _FakeChannel(["chat_postMessage"])
    client = SlackClient(fake)
    await client.send_message("", "hello")
    assert fake.calls[0][1]["channel"] == "#incidents"


async def test_slack_send_message_override_wins():
    fake = _FakeChannel(["post_message"])
    client = SlackClient(fake, tool_names={"send_message": "post_message"})
    await client.send_message("#incidents", "hello")
    name, _ = fake.calls[0]
    assert name == "post_message"


async def test_teams_send_message_uses_advertised_tool():
    fake = _FakeChannel(["send_message"])
    client = TeamsClient(fake)
    await client.send_message("#incidents", "howdy")
    name, arguments = fake.calls[0]
    assert name == "send_message"
    assert arguments == {"channel": "#incidents", "text": "howdy"}