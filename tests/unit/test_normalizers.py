from datetime import datetime

from patchthecode.domain import Severity
from patchthecode.integrations.appinsights import AppInsightsNormalizer
from patchthecode.integrations.coralogix import CoralogixNormalizer
from patchthecode.integrations.sentry import SentryNormalizer


def test_coralogix_normalizer_scales_severity():
    normal = CoralogixNormalizer().normalize({"severity": 5, "text": "boom", "applicationName": "pay"})
    assert normal.system == "coralogix"
    assert normal.severity == Severity.CRITICAL
    assert normal.service == "pay"


def test_sentry_normalizer_maps_event():
    payload = {
        "title": "AttributeError",
        "level": "fatal",
        "culprit": "src/svc.py in process",
        "message": "boom",
        "metadata": {"type": "AttributeError", "value": "None has no attr"},
        "tags": {"service": "payments"},
        "dateCreated": "2026-09-20T10:00:00Z",
    }
    normal = SentryNormalizer().normalize(payload)
    assert normal.system == "sentry"
    assert normal.severity == Severity.CRITICAL
    assert normal.exception_type == "AttributeError"
    assert normal.service == "payments"
    assert normal.stack_trace == "None has no attr"
    assert normal.timestamp == datetime.fromisoformat("2026-09-20T10:00:00Z")


def test_sentry_normalizer_defaults_when_fields_missing():
    normal = SentryNormalizer().normalize({"level": "error"})
    assert normal.severity == Severity.ERROR
    assert normal.exception_type is None


def test_appinsights_normalizer_maps_row():
    payload = {
        "severityLevel": 4,
        "message": "NPE in process",
        "operation_Name": "POST /pay",
        "exceptionType": "NullPointerException",
        "cloud_RoleName": "payments-api",
        "timestamp": "2026-09-20T10:00:00Z",
    }
    normal = AppInsightsNormalizer().normalize(payload)
    assert normal.system == "appinsights"
    assert normal.severity == Severity.CRITICAL
    assert normal.exception_type == "NullPointerException"
    assert normal.service == "payments-api"


def test_appinsights_normalizer_warning_level():
    normal = AppInsightsNormalizer().normalize({"severityLevel": 2, "message": "slow"})
    assert normal.severity == Severity.WARNING