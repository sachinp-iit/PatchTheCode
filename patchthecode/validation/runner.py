"""Run validation passes against a candidate fix.

The goal is evidence the fix is safe: unit tests, integration tests, static
checks, build, and repository CI.
"""

from __future__ import annotations

from typing import Any

from patchthecode.domain.models import FixProposal, ValidationResult


class ValidationRunner:
    """Execute configured validation adapters for a fix.

    TODO: implement adapters:
        - repository CI via the CI MCP connector (post commit -> get checks)
        - local test commands for the language detected in the repo
        - static/lint checks in the cloned working tree
    """

    async def validate(self, fix: FixProposal, ci_client: Any | None) -> ValidationResult:
        checks: list[dict[str, Any]] = []
        if ci_client is not None:
            checks.append({"name": "ci", "status": "pending"})
        return ValidationResult(passed=not checks or all(c.get("status") == "passed" for c in checks), checks=checks)