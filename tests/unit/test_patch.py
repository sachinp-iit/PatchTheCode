import pytest

from patchthecode.remediation.patch import PatchError, apply_unified_diff, diff_for_file


def test_apply_simple_removal():
    original = "a\nb\nc\nd\n"
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1,4 +1,3 @@\n a\n-b\n c\n d\n"
    assert apply_unified_diff(original, diff) == "a\nc\nd"


def test_apply_adds_lines():
    original = "x\ny\nz\n"
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1,3 +1,4 @@\n x\n y\n+z2\n z\n"
    assert apply_unified_diff(original, diff) == "x\ny\nz2\nz"


def test_apply_multiple_hunks_in_order():
    original = "1\n2\n3\n4\n5\n"
    diff = (
        "--- a/src/x.py\n+++ b/src/x.py\n"
        "@@ -1,2 +1,2 @@\n 1\n-2\n+22\n"
        "@@ -5,1 +5,1 @@\n 5\n+tail\n"
    )
    assert apply_unified_diff(original, diff) == "1\n22\n3\n4\n5\ntail"


def test_apply_no_newline_marker_ignored():
    original = "line one\nline two"
    diff = (
        "--- a/src/x.py\n+++ b/src/x.py\n@@ -1,2 +1,2 @@\n line one\n-line two\n+line two!\n\\ No newline at end of file\n"
    )
    assert apply_unified_diff(original, diff) == "line one\nline two!"


def test_apply_context_mismatch_raises():
    original = "abc\ndef\n"
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1,2 +1,2 @@\n AAA\n-b\n+c\n"
    with pytest.raises(PatchError):
        apply_unified_diff(original, diff)


def test_apply_original_shorter_than_hunk_raises():
    original = "abc\n"
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1,5 +1,5 @@\n a\n-b\n-c\n-d\n-e\n+f\n"
    with pytest.raises(PatchError):
        apply_unified_diff(original, diff)


def test_apply_trailing_context_preserved():
    original = "top\nbefore\nchanged\nafter\nbottom\n"
    diff = (
        "--- a/src/x.py\n+++ b/src/x.py\n@@ -2,3 +2,3 @@\n before\n-changed\n+CHANGED\n after\n"
    )
    assert apply_unified_diff(original, diff) == "top\nbefore\nCHANGED\nafter\nbottom"


def test_diff_for_file_extracts_exact_target():
    diff = (
        "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-a\n+b\n"
        "--- a/src/b.py\n+++ b/src/b.py\n@@ -1 +1 @@\n-x\n+y\n"
    )
    sub = diff_for_file(diff, "src/b.py")
    assert "+++ b/src/b.py" in sub
    assert "src/a.py" not in sub
    assert "-x\n+y" in sub


def test_diff_for_file_missing_target_is_empty():
    diff = "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert diff_for_file(diff, "src/other.py") == ""