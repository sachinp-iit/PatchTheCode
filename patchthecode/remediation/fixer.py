"""Create a code change in a controlled development context.

Production systems are read-only; the only write path is through a branch,
PR, and human review.
"""

from __future__ import annotations

from typing import Any

from patchthecode.domain.models import FixProposal
from patchthecode.llm.gateway import LLMGateway


class FixGenerator:
    """Generate a candidate fix from root cause + code context.

    TODO: fetch the actual source snippet through the git MCP connector and
    apply the LLM diff against a working branch (patch, commit, push).
    """

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    async def propose(self, location: Any, code_snippet: str, root_cause_text: str) -> FixProposal:
        if not code_snippet:
            raise ValueError("code_snippet is required to propose a fix")
        # util placeholder until LLM call is wired for the vertical slice
        proposal = FixProposal(
            location=location,
            diff=f"+++ b/{location.file_path or 'unknown'}\n  # TODO: generated diff",
            summary=root_cause_text.splitlines()[0] if root_cause_text else "candidate fix",
            related_files=[location.file_path] if location.file_path else [],
        )
        return proposal