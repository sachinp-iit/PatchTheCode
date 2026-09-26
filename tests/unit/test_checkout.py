from patchthecode.domain.models import CodeLocation, FixProposal
from patchthecode.validation.checkout import CheckoutBuilder

DIFF = "--- a/src/svc.py\n+++ b/src/svc.py\n@@ -1 +1 @@\n-return None\n+return valid"


def _fix() -> FixProposal:
    return FixProposal(
        location=CodeLocation(repository="acme/pay", file_path="src/svc.py"),
        diff=DIFF,
        summary="guard the provider",
        related_files=["src/svc.py"],
    )


class _FakeGit:
    def __init__(self, contents: dict[str, str] | None = None) -> None:
        self.contents = contents or {"src/svc.py": "return None"}
        self.fetched: list[str] = []

    async def resolve_file(self, location: CodeLocation) -> str:
        self.fetched.append(location.file_path or "")
        return self.contents.get(location.file_path or "", "")


async def test_checkout_materializes_patched_files(tmp_path):
    builder = CheckoutBuilder(base_dir=tmp_path)
    checkout = await builder.build(_fix(), _FakeGit())
    assert checkout is not None
    assert checkout.is_absolute()
    assert (checkout / "src" / "svc.py").read_text(encoding="utf-8") == "return valid"


async def test_checkout_skips_files_missing_from_git(tmp_path):
    builder = CheckoutBuilder(base_dir=tmp_path)
    git = _FakeGit(contents={"src/svc.py": "return None", "src/missing.py": "return None"})
    fix = _fix().model_copy(update={"related_files": ["src/svc.py", "src/absent.py"]})
    diff_multi = (
        "--- a/src/svc.py\n+++ b/src/svc.py\n@@ -1 +1 @@\n-return None\n+return valid\n"
        "--- a/src/absent.py\n+++ b/src/absent.py\n@@ -1 +1 @@\n-return None\n+return absent\n"
    )
    fix = fix.model_copy(update={"diff": diff_multi})
    checkout = await builder.build(fix, git)
    assert checkout is not None
    assert (checkout / "src" / "svc.py").exists()
    assert not (checkout / "src" / "absent.py").exists()


async def test_checkout_returns_none_without_git_connector(tmp_path):
    builder = CheckoutBuilder(base_dir=tmp_path)
    assert await builder.build(_fix(), None) is None


async def test_checkout_returns_none_when_nothing_materialized(tmp_path):
    builder = CheckoutBuilder(base_dir=tmp_path)
    fix = _fix().model_copy(update={"related_files": ["src/other.py"]})
    assert await builder.build(fix, _FakeGit()) is None