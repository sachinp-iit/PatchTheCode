from patchthecode.domain.models import CodeLocation, RootCause
from patchthecode.remediation.fixer import MODEL_UNAVAILABLE, SOURCE_UNAVAILABLE, FixGenerator


class _FakeGateway:
    def __init__(self, data: dict | None = None, raise_error: bool = False) -> None:
        self.data = data
        self.raise_error = raise_error

    async def complete_json(self, task: str, messages: list[dict[str, str]]) -> dict:
        if self.raise_error:
            raise RuntimeError("model down")
        return self.data


def _location() -> CodeLocation:
    return CodeLocation(repository="payments", file_path="src/PaymentService.java", function="processPayment")


def _root_cause() -> RootCause:
    return RootCause(
        location=_location(),
        hypothesis="unchecked null provider",
        explanation="evidence",
        confidence=0.9,
    )


def _snippet() -> str:
    return "class PaymentService { Object get() { return null; } }"


async def test_propose_parses_llm_diff():
    gateway = _FakeGateway(
        data={
            "diff": "--- a/src/PaymentService.java\n+++ b/src/PaymentService.java\n-guard",
            "summary": "guard against null provider",
            "files": ["src/PaymentService.java"],
        }
    )
    fix = await FixGenerator(gateway).propose(_location(), _snippet(), _root_cause())
    assert fix.diff.startswith("--- a/")
    assert fix.summary == "guard against null provider"
    assert fix.related_files == ["src/PaymentService.java"]
    assert fix.root_cause == _root_cause()
    assert fix.location == _location()


async def test_propose_placeholder_when_model_unavailable():
    fix = await FixGenerator(_FakeGateway(raise_error=True)).propose(_location(), _snippet(), _root_cause())
    assert fix.diff == ""
    assert fix.summary == MODEL_UNAVAILABLE
    assert fix.root_cause == _root_cause()


async def test_propose_placeholder_when_source_unavailable():
    fix = await FixGenerator(_FakeGateway(data={"diff": "ignored"})).propose(_location(), "", _root_cause())
    assert fix.diff == ""
    assert fix.summary == SOURCE_UNAVAILABLE