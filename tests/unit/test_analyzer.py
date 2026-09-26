from datetime import datetime

from patchthecode.domain import Severity
from patchthecode.domain.models import CodeLocation, Evidence, Incident, IncidentSource
from patchthecode.investigation.analyzer import INSUFFICIENT_HYPOTHESIS, RootCauseAnalyzer


class _FakeGateway:
    def __init__(self, data: dict | None = None, raise_error: bool = False) -> None:
        self.data = data
        self.raise_error = raise_error

    async def complete_json(self, task: str, messages: list[dict[str, str]]) -> dict:
        if self.raise_error:
            raise RuntimeError("model down")
        if self.data is None:
            raise RuntimeError("no data")
        return self.data


def _incident() -> Incident:
    ts = datetime.utcnow()
    return Incident(
        id="t:1",
        fingerprint="fp",
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={"service": "payments-api"},
    )


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            kind="query_logs",
            source_system="coralogix_mcp",
            content={"text": "NullPointerException at PaymentService.processPayment"},
        )
    ]


async def test_no_evidence_returns_insufficient_without_calling_gateway():
    analyzer = RootCauseAnalyzer(gateway=_FakeGateway(data={"ok": True}))
    cause = await analyzer.analyze(_incident(), [])
    assert cause.hypothesis == INSUFFICIENT_HYPOTHESIS
    assert cause.confidence == 0.0
    assert cause.location.repository == "unknown"


async def test_llm_result_parsed_into_root_cause():
    data = {
        "hypothesis": "Unchecked null payment provider",
        "confidence": 0.9,
        "repository": "payments",
        "file_path": "src/main/java/PaymentService.java",
        "function": "processPayment",
        "branch": "main",
        "commit": "abc123",
        "explanation": "Logs spike after deploy v2.8.4",
        "evidence_refs": ["query_logs"],
    }
    analyzer = RootCauseAnalyzer(gateway=_FakeGateway(data=data))
    cause = await analyzer.analyze(_incident(), _evidence())
    assert cause.hypothesis == "Unchecked null payment provider"
    assert cause.confidence == 0.9
    assert cause.location == CodeLocation(
        repository="payments",
        branch="main",
        commit="abc123",
        file_path="src/main/java/PaymentService.java",
        function="processPayment",
    )
    assert cause.evidence_refs == ["query_logs"]


async def test_gateway_failure_falls_back_to_insufficient():
    analyzer = RootCauseAnalyzer(gateway=_FakeGateway(raise_error=True))
    cause = await analyzer.analyze(_incident(), _evidence())
    assert cause.hypothesis == INSUFFICIENT_HYPOTHESIS
    assert cause.location.repository == "unknown"


async def test_missing_fields_default_and_confidence_clamped():
    data = {"hypothesis": "h", "confidence": 5.0, "explanation": "e"}
    analyzer = RootCauseAnalyzer(gateway=_FakeGateway(data=data))
    cause = await analyzer.analyze(_incident(), _evidence())
    assert cause.confidence == 1.0
    assert cause.location.repository == "unknown"
    assert cause.location.file_path is None


async def test_invalid_payload_falls_back_to_insufficient():
    analyzer = RootCauseAnalyzer(gateway=_FakeGateway(data={"hypothesis": {}}))  # non-string hypothesis
    cause = await analyzer.analyze(_incident(), _evidence())
    assert cause.hypothesis == INSUFFICIENT_HYPOTHESIS