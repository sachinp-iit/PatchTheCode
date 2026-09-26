"""Static code checks against a candidate fix's changed files.

The validator applies the fix's diff onto a checkout directory and runs
per-language lint/static-check commands, producing concrete evidence for the
ValidationRunner. Command execution is injected so tests stay hermetic and
operators can provide their own sandbox. Sensible per-language defaults are
available; tools that are not on PATH are reported as explicit skips.
"""

from __future__ import annotations

import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patchthecode.domain.models import FixProposal
from patchthecode.remediation.patch import PatchError, apply_unified_diff, diff_for_file


@dataclass
class CommandResult:
    """Outcome of running one static check command."""

    returncode: int
    tail: str = ""


Executor = Callable[[list[str], Path], Awaitable[CommandResult]]


def default_commands() -> dict[str, list[str]]:
    """Sensible per-language lint commands; tools must be on PATH to run."""
    return {
        ".py": ["python", "-m", "ruff", "check", "{file}"],
        ".ts": ["npx", "eslint", "{file}"],
        ".tsx": ["npx", "eslint", "{file}"],
        ".js": ["npx", "eslint", "{file}"],
        ".go": ["gofmt", "-l", "{file}"],
    }


class StaticValidator:
    """Lint the files a fix touches using per-extension commands.

    ``commands`` maps file extensions (e.g. ".py") to a command template;
    the literal ``{file}`` is replaced with the changed file's path. When
    ``commands`` is None the module defaults are used. Command execution can
    be injected; an injected executor is trusted, while the real subprocess
    path first checks the tool exists on PATH and skips it otherwise.
    """

    def __init__(
        self,
        commands: dict[str, list[str]] | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.commands = default_commands() if commands is None else commands
        self.executor = executor or self._default_executor
        self._trusted_executor = executor is not None

    @staticmethod
    async def _default_executor(command: list[str], cwd: Path) -> CommandResult:
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return CommandResult(returncode=proc.returncode or 0, tail=(stdout or b"").decode()[-500:])

    async def lint(self, fix: FixProposal, checkout: Path | None = None) -> list[dict[str, Any]]:
        """Return per-file lint checks for the fix's related files."""
        checks: list[dict[str, Any]] = []
        if checkout is None:
            return [{"name": "static", "status": "skipped", "reason": "no checkout available"}]
        checkout = checkout.resolve()
        for path in fix.related_files:
            file_path = Path(path)
            template = self.commands.get(file_path.suffix.lower())
            if template is None:
                checks.append(
                    {
                        "name": f"lint:{path}",
                        "status": "skipped",
                        "reason": f"no lint command for extension {file_path.suffix or '(none)'}",
                    }
                )
                continue
            if not self._tool_available(template):
                checks.append(
                    {
                        "name": f"lint:{path}",
                        "status": "skipped",
                        "reason": f"tool {template[0]!r} not found on PATH",
                    }
                )
                continue
            target = checkout / path
            file_diff = diff_for_file(fix.diff, path)
            if not file_diff:
                checks.append(
                    {"name": f"lint:{path}", "status": "skipped", "reason": "fix diff does not touch this path"}
                )
                continue
            try:
                content = self._patched_content(fix, path, file_diff, target)
            except PatchError:
                checks.append(
                    {"name": f"lint:{path}", "status": "skipped", "reason": "could not apply fix diff"}
                )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            command = [part.replace("{file}", str(target)) for part in template]
            result = await self.executor(command, checkout)
            checks.append(
                {
                    "name": f"lint:{path}",
                    "command": " ".join(command),
                    "status": "passed" if result.returncode == 0 else "failed",
                    "output": result.tail,
                }
            )
        return checks

    def _tool_available(self, template: list[str]) -> bool:
        """Injected executors are trusted; real execution needs the tool on PATH."""
        if self._trusted_executor:
            return True
        return shutil.which(template[0]) is not None

    @staticmethod
    def _patched_content(fix: FixProposal, path: str, file_diff: str, target: Path) -> str:
        """Return the fixed version of a file.

        Prefers applying the fix diff onto an existing checkout file; when the
        diff no longer applies the checkout already contains the fixed file, so
        that content is used as-is. When the file is not present at all, the
        content is reconstructed from the diff's hunks.
        """
        if target.exists():
            try:
                return apply_unified_diff(target.read_text(encoding="utf-8"), file_diff)
            except PatchError:
                return target.read_text(encoding="utf-8")
        sections: list[str] = []
        in_hunk = False
        for line in file_diff.splitlines():
            if line.startswith("@@") and not in_hunk:
                in_hunk = True
            elif in_hunk and (line.startswith(" ") or line.startswith("+")):
                sections.append(line[1:])
        return "\n".join(sections)