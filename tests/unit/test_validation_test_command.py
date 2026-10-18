"""Test command wiring: ValidationRunner runs the configured test command in the checkout."""

import sys

from patchthecode.domain.models import CodeLocation, FixProposal, RootCause
from patchthecode.validation.runner import ValidationRunner


def _fix(tmp_path=None):
    return FixProposal(
        location=CodeLocation(repository="r", file_path="a.py"),
        diff="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n",
        summary="s",
        root_cause=RootCause(hypothesis="bug", location=CodeLocation(repository="r", file_path="a.py"), explanation="e"),
        related_files=["a.py"],
    )


async def test_validate_runs_test_command_in_checkout(tmp_path):
    runner = ValidationRunner(test_command=f"{sys.executable} -c 'print(1)'")
    result = await runner.validate(_fix(), checkout=tmp_path)
    test_checks = [c for c in result.checks if c["name"] == "test"]
    assert len(test_checks) == 1
    assert test_checks[0]["status"] == "passed"


async def test_validate_failing_test_command_fails_validation(tmp_path):
    runner = ValidationRunner(test_command=f"{sys.executable} -c 'raise SystemExit(1)'")
    result = await runner.validate(_fix(), checkout=tmp_path)
    assert not result.passed
    test_checks = [c for c in result.checks if c["name"] == "test"]
    assert test_checks[0]["status"] == "failed"


async def test_validate_skips_test_command_when_no_checkout():
    runner = ValidationRunner(test_command=f"{sys.executable} -c 'print(1)'")
    result = await runner.validate(_fix(), checkout=None)
    assert not any(c["name"] == "test" for c in result.checks)
