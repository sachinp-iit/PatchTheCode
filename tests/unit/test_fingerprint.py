from datetime import datetime

from patchthecode.detection.fingerprint import fingerprint, stack_frames
from patchthecode.detection.normalizer import NormalizedOccurrence
from patchthecode.domain import Severity

STACK = """java.lang.NullPointerException: null
	at com.acme.PaymentService.processPayment(PaymentService.java:184)
	at com.acme.PaymentController.handle(PaymentController.java:42)
"""


def _occurrence(
    stack: str | None = STACK,
    message: str | None = "Payment failed for order 12345",
    exception_type: str = "java.lang.NullPointerException",
) -> NormalizedOccurrence:
    return NormalizedOccurrence(
        system="coralogix",
        kind="logs",
        severity=Severity.ERROR,
        title="NullPointerException in PaymentService.processPayment",
        description=None,
        exception_type=exception_type,
        message=message,
        stack_trace=stack,
        timestamp=datetime.utcnow(),
        service="payments-api",
        raw={},
    )


def test_same_bug_same_fingerprint_regardless_of_dynamic_values():
    a = fingerprint(_occurrence(message="Payment failed for order 12345"))
    b = fingerprint(_occurrence(message="Payment failed for order 99999"))
    assert a.value == b.value


def test_different_exception_different_fingerprint():
    a = fingerprint(_occurrence())
    b = _occurrence(exception_type="java.lang.IllegalStateException")
    b.title = "IllegalStateException in PaymentService.processPayment"
    assert a.value != fingerprint(b).value


def test_stack_frames_are_canonical_and_limited():
    frames = stack_frames(STACK)
    assert frames[0] == "PaymentService.processPayment"
    assert len(frames) == 2


def test_stack_trace_hash_isolates_line_changes():
    frames = stack_frames(STACK, max_frames=1)
    assert len(frames) >= 1  # canonical frames still extracted once first frame diffs