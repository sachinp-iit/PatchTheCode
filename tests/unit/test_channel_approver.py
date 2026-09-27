"""The ChannelApprover resolves write-approval by reading chat replies."""

from patchthecode.notifications.render import render_approval_request
from patchthecode.security.approver import ChannelApprover


class _ReplyFacade:
    """A chat facade that echoes posted prompts and returns scripted replies."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = replies
        self.posted: list[tuple[str, str]] = []
        self.markers: list[str] = []

    async def send_message(self, channel: str, text: str) -> bool:
        self.posted.append((channel, text))
        return True

    async def read_messages(self, channel: str, marker: str | None = None) -> list[dict]:
        self.markers.append(marker)
        if marker is None:
            return []
        return [
            {**reply, "text": f"{marker} {reply.get('text', '')}".strip()}
            for reply in self.replies
        ]


def _payload() -> dict:
    return {
        "repository": "payments",
        "head_branch": "patchthecode/n:1",
        "base_branch": "main",
        "files": ["src/svc.py"],
    }


async def test_render_approval_request_embeds_code_and_payload():
    text = render_approval_request("open_pull_request", _payload(), code="abc123", timeout_seconds=60)
    assert "abc123" in text
    assert "open_pull_request" in text
    assert "payments" in text
    assert "src/svc.py" in text


async def test_approve_on_affirmative_text_reply():
    facade = _ReplyFacade([{"reactions": [], "text": "approve"}])
    approver = ChannelApprover(facade, timeout_seconds=2, poll_seconds=0.01)
    assert await approver.approve("open_pull_request", _payload()) is True
    assert facade.posted[0][1].endswith("within 2 seconds.")


async def test_reject_on_negative_text_reply():
    facade = _ReplyFacade([{"reactions": [], "text": "reject this"}])
    approver = ChannelApprover(facade, timeout_seconds=2, poll_seconds=0.01)
    assert await approver.approve("open_pull_request", _payload()) is False


async def test_approve_via_approving_reaction():
    facade = _ReplyFacade([{"reactions": [{"name": "white_check_mark"}], "text": ""}])
    approver = ChannelApprover(facade, timeout_seconds=2, poll_seconds=0.01)
    assert await approver.approve("open_pull_request", _payload()) is True


async def test_negative_reaction_trumps_approving_text():
    facade = _ReplyFacade([{"reactions": [{"name": "thumbsdown"}], "text": "approve"}])
    approver = ChannelApprover(facade, timeout_seconds=2, poll_seconds=0.01)
    assert await approver.approve("open_pull_request", _payload()) is False


async def test_timeout_blocks_by_default_and_prompts_itself():
    facade = _ReplyFacade([])
    approver = ChannelApprover(facade, timeout_seconds=0.05, poll_seconds=0.01)
    assert await approver.approve("open_pull_request", _payload()) is False
    assert approver.prompts_itself is True


async def test_approver_queries_with_a_marker():
    facade = _ReplyFacade([{"reactions": [], "text": "no"}])
    approver = ChannelApprover(facade, timeout_seconds=2, poll_seconds=0.01)
    await approver.approve("open_pull_request", _payload())
    assert facade.markers and all(marker is not None for marker in facade.markers)