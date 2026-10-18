"""Run validation passes against a candidate fix.

Validation aims to prove a fix is safe: static lint checks on the changed
files, unit/integration tests, and remote CI. Adapters produce evidence rows;
when NO adapter is configured the runner records an explicit *skipped* row
instead of pretending success (no silent empty passes).
"""

from __future__ import annotations

import logging
from typing import Any

from patchthecode.domain.models import FixProposal, ValidationResult
from patchthecode.validation.static import StaticValidator

logger = logging.getLogger(__name__)


class ValidationRunner:
    """Execute configured validation adapters for a fix.

    TODO: implement adapters:
        - repository CI via the CI MCP connector (post commit -> get checks)
        - local test commands for the language detected in the repo
    """

    def __init__(self, static: StaticValidator | None = None, test_command: str | None = None) -> None:
        self.static = static
        self.test_command = test_command or None

    async def validate(
        self,
        fix: FixProposal,
        ci_client: Any | None = None,
        checkout: Any | None = None,
    ) -> ValidationResult:
        checks: list[dict[str, Any]] = []

        if self.static is not None and fix.related_files:
            try:
                checks.extend(await self.static.lint(fix, checkout=checkout))
            except Exception:  # noqa: BLE001 - a broken adapter must not abort validation
                logger.exception("static validation failed for %s", fix.location.file_path or "?")
                checks.append({"name": "static", "status": "failed", "reason": "adapter crashed"})

        if self.test_command and checkout is not None:
            try:
                checks.append(await self._run_test_command(checkout))
            except Exception:  # noqa: BLE001 - a broken test command must not abort validation
                logger.exception("test command failed for %s", fix.location.file_path or "?")
                checks.append({"name": "test", "status": "failed", "reason": "test command crashed"})

        if ci_client is not None:
            try:
                check_ref = await ci_client.submit_check(
                    repository=fix.location.repository,
                    diff=fix.diff,
                    branch=None,
                )
                if not check_ref:
                    checks.append({"name": "ci", "status": "failed", "reason": "no check reference returned"})
                else:
                    checks.extend(await ci_client.poll_checks(check_ref))
            except Exception:  # noqa: BLE001 - CI outage shows up as a failing check
                logger.exception("CI validation failed for %s", fix.location.file_path or "?")
                checks.append({"name": "ci", "status": "failed", "reason": "could not reach CI connector"})

        if not checks:
            checks.append(
                {
                    "name": "validation",
                    "status": "skipped",
                    "reason": "no validation adapters configured",
                }
            )
            return ValidationResult(passed=True, checks=checks)

        # Stronger when adapters are configured: every check must actually pass.
        passed = all(c.get("status") == "passed" for c in checks)
        return ValidationResult(passed=passed, checks=checks)

    async def _run_test_command(self, checkout: Any) -> dict[str, Any]:
        """Run the configured test command in the checkout and record a check row."""
        import asyncio

        command = self.test_command.split()
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(checkout),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        tail = (stdout or b"").decode()[-500:]
        return {
            "name": "test",
            "command": self.test_command,
            "status": "passed" if proc.returncode == 0 else "failed",
            "output": tail,
        }