"""Slack and Teams facades post messages through a communication MCP connector."""

from patchthecode.integrations.slack import SlackClient
from patchthecode.integrations.teams import TeamsClient


class _FakeChannel:
    def __init__(self, tools: list[str], handler=None) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict]] = []
        self.handler = handler

    async def list_tools(self) -> list[dict]:
        return [{"name": t} for t in self.tools]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self.calls.append((name, arguments or {}))
        if self.handler is not None:
            return await self.handler(name, arguments or {})
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


async def test_slack_read_messages_normalizes_and_filters_by_marker():
    async def handler(name: str, arguments: dict) -> dict:
        return {
            "content": "ok",
            "structured": {
                "messages": [
                    {
                        "ts": "1",
                        "text": "abc123 approve please",
                        "reactions": [{"name": "white_check_mark"}],
                    },
                    {"message_ts": "2", "content": "unrelated", "reactions": []},
                ]
            },
        }

    fake = _FakeChannel(["conversations_history"], handler=handler)
    client = SlackClient(fake)
    matched = await client.read_messages("#incidents", marker="abc123")
    assert len(matched) == 1
    assert matched[0]["ts"] == "1"
    assert "approve" in matched[0]["text"]
    assert matched[0]["reactions"] == [{"name": "white_check_mark"}]
    assert fake.calls[0][0] == "conversations_history"
    assert fake.calls[0][1] == {"channel": "#incidents"}


async def test_slack_read_messages_returns_all_without_marker():
    async def handler(name: str, arguments: dict) -> dict:
        return {"content": "ok", "structured": {"messages": [{"text": "one"}, {"text": "two"}]}}

    fake = _FakeChannel(["conversations_history"], handler=handler)
    client = SlackClient(fake)
    assert len(await client.read_messages("#incidents")) == 2


async def test_teams_read_messages_uses_advertised_tool():
    async def handler(name: str, arguments: dict) -> dict:
        return {"content": "ok", "structured": {"messages_list": [{"id": "9", "text": "xyz rejected"}]}}

    fake = _FakeChannel(["list_messages"], handler=handler)
    client = TeamsClient(fake)
    messages = await client.read_messages("#incidents", marker="xyz")
    assert len(messages) == 1
    assert messages[0]["ts"] == "9"
    assert messages[0]["text"] == "xyz rejected"