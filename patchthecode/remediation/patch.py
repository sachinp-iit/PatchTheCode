"""Apply unified diffs (as produced by the fix generator) to source text.

This is the mechanism that turns an LLM-produced diff into real file
content for the git write path. It supports standard unified-diff hunks:
context, removed, and added lines, plus the `\\ No newline` marker.
"""

from __future__ import annotations

import re

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FILE_HEADER = re.compile(r"^\+\+\+ \S+")


class PatchError(RuntimeError):
    """Raised when a diff cannot be applied to the given source."""


def _parse_hunk_header(line: str) -> int:
    match = _HUNK_HEADER.match(line)
    if match is None:
        raise PatchError(f"malformed hunk header: {line!r}")
    return int(match.group(1))  # old-file start line (1-based)


def apply_unified_diff(original: str, diff: str) -> str:
    """Apply `diff` to `original` and return the resulting text.

    The diff is assumed to target a single file. Line counts in hunk headers
    are treated as hints; the body markers drive the application.
    """
    if not original and not diff:
        raise PatchError("both original and diff are empty")
    orig_lines = original.splitlines()
    out: list[str] = []
    position = 0  # 0-based index of next original line to consume
    in_hunk = False

    for line in diff.splitlines():
        if line.startswith("\\"):
            continue  # "\\ No newline at end of file"
        if line.startswith("@@"):
            position, in_hunk = _start_hunk(orig_lines, out, position, line)
            continue
        if not in_hunk:
            continue  # file headers and noise
        if line.startswith(" "):
            _consume(orig_lines, position, line[1:], out, position)
            position += 1
        elif line.startswith("-"):
            _consume(orig_lines, position, line[1:], None, position)
            position += 1
        elif line.startswith("+"):
            out.append(line[1:])
        else:
            in_hunk = False

    out.extend(orig_lines[position:])
    return "\n".join(out)


def _start_hunk(
    orig_lines: list[str],
    out: list[str],
    position: int,
    header: str,
) -> tuple[int, bool]:
    old_start = _parse_hunk_header(header)
    target = old_start - 1
    if target < position:
        raise PatchError(f"hunk {header!r} overlaps already-applied region")
    out.extend(orig_lines[position:target])
    return target, True


def _consume(
    orig_lines: list[str],
    position: int,
    expected: str,
    out: list[str] | None,
    line_no: int,
) -> None:
    if position >= len(orig_lines):
        raise PatchError(f"diff wants line {line_no + 1} but source has none")
    actual = orig_lines[position]
    if expected != actual:
        raise PatchError(
            f"context mismatch at source line {line_no + 1}: "
            f"expected {expected!r}, found {actual!r}"
        )
    if out is not None:
        out.append(actual)


def diff_for_file(diff: str, path: str) -> str:
    """Extract the portion of `diff` targeting `path`.

    Splits the diff per `+++ path` header and returns the best match; empty
    when the file is not touched (or the diff has no file headers).
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            current = None  # begin a new file section; keep only +++ targets
            continue
        match = _FILE_HEADER.match(line)
        if match:
            header = match.group(0)
            current = header.split("+++ ", 1)[1].strip()
            sections.setdefault(current, []).append(line)
        elif current is not None:
            sections[current].append(line)

    target = path.strip().lstrip("/")
    exact = next((p for p in sections if p.rstrip("/").endswith(target)), None)
    if exact is None:
        return ""
    return "\n".join(sections[exact])