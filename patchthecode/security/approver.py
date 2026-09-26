"""Approval gates for write-capable agent actions.

PatchTheCode's design principle is "human review": production systems stay
read-only and code changes land as pull requests. The approver is the seam
where that policy is enforced. The default blocks write actions and logs
them; automated approval only happens when explicitly opted in.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


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