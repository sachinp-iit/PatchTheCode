"""Approval gates for write-capable agent actions.

PatchTheCode's design principle is "human review": production systems stay
read-only and code changes land as pull requests. The approver is the seam
where that policy is enforced. The default blocks write actions and logs
them; automated approval only happens when explicitly opted in.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any, Protocol

from patchthecode.notifications.render import render_approval_request

logger = logging.getLogger(__name__)

_APPROVE_WORDS = ("approve", "approved", "lgtm", "ship it", "yes", "ok")
_REJECT_WORDS = ("reject", "rejected", "deny", "denied", "no", "nope", "block")
_APPROVE_REACTIONS = frozenset({"white_check_mark", "✅", "thumbsup", "+1", "+1:", "plus_one"})
_REJECT_REACTIONS = frozenset({"x", "❌", "thumbsdown", "-1", "-1:", "minus_one"})


class Approver(Protocol):
    async def approve(self, action: str, payload: dict[str, Any]) -> bool: ...


class AutoApprover:
    """Approves every action.

    Only construct this when the operator explicitly opts in (env flag or
    CLI switch); it exists for automated/test deployments.
    """

    async def approve(self, action: str, payload: dict[str, Any]) -> bool:
        logger.info("auto-approving %s: %s", action, payload)
        return True


class LoggingApprover:
    """Default approver: record the pending action and block it.

    The logged payload is the review bundle a human can inspect; wiring a
    real interactive prompt here (CLI or chat) is the natural next step.
    """

    async def approve(self, action: str, payload: dict[str, Any]) -> bool:
        logger.warning("BLOCKED %s (no approver configured). Pending payload: %s", action, payload)
        return False


class ChannelApprover:
    """Approver that prompts in a chat channel and reads the reply.

    Posts an approval request tagged with a correlation code, polls the
    channel for a reply or reaction carrying that code, and resolves to
    True/False. When nobody answers before the timeout the action stays
    blocked (safe default). The facade must expose ``send_message`` and
    ``read_messages`` — the Slack/Teams adapters both provide them.
    """

    prompts_itself = True

    def __init__(
        self,
        facade: Any,
        channel: str = "#incidents",
        timeout_seconds: int = 300,
        poll_seconds: float = 5,
    ) -> None:
        self.facade = facade
        self.channel = channel
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    async def approve(self, action: str, payload: dict[str, Any]) -> bool:
        code = uuid.uuid4().hex[:8]
        prompt = render_approval_request(action, payload, code, self.timeout_seconds)
        await self.facade.send_message(self.channel, prompt)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                replies = await self.facade.read_messages(self.channel, marker=code)
            except Exception:  # noqa: BLE001 - a flaky channel means "not yet decided"
                replies = []
            decision = self._decide(replies)
            if decision is not None:
                logger.info(
                    "approval for %s resolved: %s",
                    action,
                    "approved" if decision else "rejected",
                )
                return decision
            await asyncio.sleep(self.poll_seconds)
        logger.warning("approval for %s timed out after %ss; blocking", action, self.timeout_seconds)
        return False

    @staticmethod
    def _decide(messages: list[dict[str, Any]]) -> bool | None:
        """A decision from channel replies; None means no signal yet.

        Text is matched on whole words; reactions are matched verbatim,
        favoring a rejection when a message carries conflicting signals.
        """
        for message in messages:
            text = " ".join((message.get("text") or "").lower().split())
            for word in _REJECT_WORDS:
                if re.search(rf"\b{re.escape(word)}\b", text):
                    return False
            for reaction in message.get("reactions") or []:
                name = (reaction.get("name") or "").lower()
                if name in _REJECT_REACTIONS:
                    return False
            for word in _APPROVE_WORDS:
                if re.search(rf"\b{re.escape(word)}\b", text):
                    return True
            for reaction in message.get("reactions") or []:
                name = (reaction.get("name") or "").lower()
                if name in _APPROVE_REACTIONS:
                    return True
        return None