from pathlib import Path

from patchthecode.domain.models import CodeLocation, FixProposal
from patchthecode.validation.runner import ValidationRunner
from patchthecode.validation.static import CommandResult, StaticValidator

DIFF = "--- a/src/svc.py\n+++ b/src/svc.py\n@@ -1 +1 @@\n-return None\n+return valid"


def _fix(related_files: list[str] | None = None) -> FixProposal:
    return FixProposal(
        location=CodeLocation(repository="acme/pay", file_path="src/svc.py"),
        diff=DIFF,
        summary="guard the provider",
        related_files=related_files or ["src/svc.py"],
    )


class _ScriptedExecutor:
    """Return a configured verdict for each file the validator checks."""

    def __init__(self, verdicts: dict[str, int] | None = None) -> None:
        self.verdicts = verdicts or {}

    async def __call__(self, command: list[str], cwd: Path) -> CommandResult:
        file_path = Path(command[-1])
        return CommandResult(self.verdicts.get(str(file_path), 0), file_path.read_text(encoding="utf-8"))


def _checkout(tmp_path) -> Path:
    checkout = tmp_path / "co"
    checkout.mkdir()
    target = checkout / "src" / "svc.py"
    target.parent.mkdir(parents=True)
    target.write_text("return None", encoding="utf-8")
    return checkout


async def test_static_validator_passes_when_patch_lints_clean(tmp_path):
    checkout = _checkout(tmp_path)
    validator = StaticValidator(commands={".py": ["check", "{file}"]}, executor=_ScriptedExecutor())
    checks = await validator.lint(_fix(), checkout=checkout)
    assert checks[0]["status"] == "passed"
    assert (checkout / "src" / "svc.py").read_text(encoding="utf-8") == "return valid"


async def test_static_validator_fails_when_linter_returns_error(tmp_path):
    checkout = _checkout(tmp_path)
    target = checkout / "src" / "svc.py"
    validator = StaticValidator(
        commands={".py": ["check", "{file}"]},
        executor=_ScriptedExecutor({str(target): 1}),
    )
    checks = await validator.lint(_fix(), checkout=checkout)
    assert checks[0]["status"] == "failed"


async def test_static_validator_skips_without_checkout():
    validator = StaticValidator(commands={".py": ["check", "{file}"]}, executor=_ScriptedExecutor())
    checks = await validator.lint(_fix(), checkout=None)
    assert checks[0]["status"] == "skipped"
    assert "no checkout" in checks[0]["reason"]


async def test_static_validator_skips_unconfigured_extension(tmp_path):
    checkout = _checkout(tmp_path)
    validator = StaticValidator(commands={".py": ["check", "{file}"]}, executor=_ScriptedExecutor())
    checks = await validator.lint(_fix(related_files=["src/svc.js"]), checkout=checkout)
    assert checks[0]["status"] == "skipped"
    assert "no lint command" in checks[0]["reason"]


async def test_static_validator_skips_path_untouched_by_diff(tmp_path):
    checkout = tmp_path / "co"
    checkout.mkdir()
    validator = StaticValidator(commands={".py": ["check", "{file}"]}, executor=_ScriptedExecutor())
    checks = await validator.lint(_fix(related_files=["src/other.py"]), checkout=checkout)
    assert checks[0]["status"] == "skipped"
    assert "does not touch" in checks[0]["reason"]


class _FakeCIClient:
    def __init__(self, status: str = "passed") -> None:
        self.status = status
        self.submitted: list[tuple] = []

    async def submit_check(self, repository: str, diff: str, branch: str | None = None) -> str:
        self.submitted.append((repository, diff, branch))
        return "chk-1"

    async def poll_checks(self, check_ref: str) -> list[dict[str, str]]:
        assert check_ref == "chk-1"
        return [{"name": "ci", "status": self.status}]


async def test_runner_reports_explicit_skip_when_no_adapters():
    result = await ValidationRunner().validate(_fix())
    assert result.passed is True
    assert len(result.checks) == 1
    assert result.checks[0]["status"] == "skipped"
    assert "no validation adapters configured" in result.checks[0]["reason"]


async def test_runner_strict_when_ci_client_passes():
    result = await ValidationRunner().validate(_fix(), ci_client=_FakeCIClient("passed"))
    assert result.passed is True
    assert result.checks == [{"name": "ci", "status": "passed"}]


async def test_runner_fails_when_ci_check_fails():
    result = await ValidationRunner().validate(_fix(), ci_client=_FakeCIClient("failed"))
    assert result.passed is False
    assert result.checks == [{"name": "ci", "status": "failed"}]


async def test_runner_strict_with_static_validator(tmp_path):
    checkout = _checkout(tmp_path)
    target = checkout / "src" / "svc.py"
    fail = StaticValidator(
        commands={".py": ["check", "{file}"]},
        executor=_ScriptedExecutor({str(target): 1}),
    )
    result = await ValidationRunner(static=fail).validate(_fix(), checkout=checkout)
    assert result.passed is False
    assert result.checks[0]["status"] == "failed"


def test_static_validator_uses_default_commands_when_none_given():
    validator = StaticValidator(executor=_ScriptedExecutor())
    assert validator.commands[".py"] == ["python", "-m", "ruff", "check", "{file}"]
    assert ".go" in validator.commands


async def test_static_validator_default_template_runs_against_patched_file(tmp_path):
    checkout = _checkout(tmp_path)
    seen: list[list[str]] = []

    async def recording_executor(command: list[str], cwd: Path) -> CommandResult:
        seen.append(command)
        return CommandResult(0, "")

    validator = StaticValidator(commands=None, executor=recording_executor)
    checks = await validator.lint(_fix(), checkout=checkout)
    assert checks[0]["status"] == "passed"
    assert len(seen) == 1
    assert seen[0][0] == "python"
    assert seen[0][-1] == str(checkout / "src" / "svc.py")


async def test_real_executor_skips_when_tool_missing(tmp_path, monkeypatch):
    checkout = _checkout(tmp_path)
    monkeypatch.setattr("patchthecode.validation.static.shutil.which", lambda _name: None)
    validator = StaticValidator(commands=None, executor=None)
    checks = await validator.lint(_fix(), checkout=checkout)
    assert checks[0]["status"] == "skipped"
    assert "not found on PATH" in checks[0]["reason"]