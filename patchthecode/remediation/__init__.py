"""Remediation: generating a fix in a controlled development context."""

from patchthecode.remediation.fixer import FixGenerator
from patchthecode.remediation.patch import PatchError, apply_unified_diff, diff_for_file

__all__ = ["FixGenerator", "PatchError", "apply_unified_diff", "diff_for_file"]