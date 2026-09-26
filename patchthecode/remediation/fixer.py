"""Create a code change in a controlled development context.

Production systems are read-only; the only write path is through a branch,
PR, and human review. The fix diff is produced by the LLM from the located
root cause and the current source.
"""

from __future__ import annotations

import logging

from patchthecode.domain.models import CodeLocation, FixProposal, RootCause
from patchthecode.llm.gateway import LLMGateway
from patchthecode.llm.prompts import generate_fix_prompt

logger = logging.getLogger(__name__)

SOURCE_UNAVAILABLE = "Code snippet unavailable; fix not generated"
MODEL_UNAVAILABLE = "Fix generation failed (model unavailable or invalid response)"


class FixGenerator:
    """Generate a candidate fix from root cause + code context."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    async def propose(
        self,
        location: CodeLocation,
        code_snippet: str,
        root_cause: RootCause,
    ) -> FixProposal:
        if not code_snippet:
            logger.info("cannot generate fix for %s: source snippet unavailable", location.repository)
            return self._placeholder(location, root_cause, SOURCE_UNAVAILABLE)

        messages = generate_fix_prompt(location.model_dump(), code_snippet, root_cause.hypothesis)
        try:
            data = await self.gateway.complete_json("codegen", messages)
            diff = str(data.get("diff") or "").strip()
            return FixProposal(
                location=location,
                diff=diff,
                summary=str(data.get("summary") or ""),
                root_cause=root_cause,
                related_files=[str(f) for f in (data.get("files") or [])],
            )
        except Exception:  # noqa: BLE001 - never let a failing model block the report
            logger.warning("fix generation failed for %s; returning placeholder", location.repository, exc_info=True)
            return self._placeholder(location, root_cause, MODEL_UNAVAILABLE)

    def _placeholder(self, location: CodeLocation, root_cause: RootCause, reason: str) -> FixProposal:
        return FixProposal(
            location=location,
            diff="",
            summary=reason,
            root_cause=root_cause,
        )