"""Materialize a working-checkout view of a fix from the git connector.

The agent's fix is a diff over sources it can fetch read-only from the git
MCP connector. ``CheckoutBuilder`` fetches each touched file, applies the fix,
and lays the result into a temp directory so local validators have a real
tree to lint. Nothing is cloned or written back; this is a pure read path.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from patchthecode.domain.models import CodeLocation, FixProposal
from patchthecode.remediation.patch import PatchError, apply_unified_diff, diff_for_file


class CheckoutBuilder:
    """Build a temp checkout containing the fixed versions of changed files."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir

    async def build(self, fix: FixProposal, git_client: Any | None) -> Path | None:
        """Fetch the files the fix touches, patch them, and return a tree path.

        Returns None when there is no git connector or nothing could be
        materialized (individual un-fetchable/un-applyable files are skipped).
        """
        if git_client is None:
            return None
        checkout = self._new_dir()
        wrote_any = False
        for path in fix.related_files:
            file_diff = diff_for_file(fix.diff, path)
            if not file_diff:
                continue
            try:
                original = await git_client.resolve_file(
                    CodeLocation(repository=fix.location.repository, file_path=path)
                )
            except Exception:  # noqa: BLE001 - a missed source just means no check for that file
                continue
            target = checkout / path
            try:
                content = apply_unified_diff(original, file_diff)
            except PatchError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            wrote_any = True
        if not wrote_any:
            return None
        return checkout

    def _new_dir(self) -> Path:
        if self.base_dir is not None:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(dir=str(self.base_dir), prefix="checkout-"))
        return Path(tempfile.mkdtemp(prefix="patchthecode-checkout-"))