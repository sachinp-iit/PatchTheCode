"""Convert webhook alert payloads into incidents.

Two shapes are accepted: a full `Incident` payload (what `replay` consumes) and
a minimal alert envelope (`title` plus optional service/severity/etc.) that is
normalized, fingerprinted, and built into an incident exactly like a live
occurrence would be, so deduplication and the learning loop keep working for
pushed alerts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ValidationError

from patchthecode.detection.fingerprint import fingerprint
from patchthecode.detection.normalizer import NormalizedOccurrence, build_incident
from patchthecode.domain import Severity
from patchthecode.domain.models import Incident


class InvalidIncidentPayload(ValueError):
    """The webhook body is neither an incident nor a usable alert envelope."""


def incident_from_payload(payload: Any) -> Incident:
    """Build an incident from a webhook body.

    Raises `InvalidIncidentPayload` when the body is not an incident and
    carries no usable alert information.
    """
    if not isinstance(payload, dict):
        raise InvalidIncidentPayload("payload must be a JSON object")
    try:
        return Incident.model_validate(payload)
    except ValidationError:
        pass  # not a full incident; try the alert-envelope shape

    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise InvalidIncidentPayload('payload needs a "title" or a full incident shape')

    last_seen = _time(payload.get("last_seen")) or datetime.utcnow()
    first_seen = _time(payload.get("first_seen")) or last_seen
    occurrence = NormalizedOccurrence(
        system=_text(payload.get("system")) or "webhook",
        kind=_text(payload.get("kind")) or "alert",
        severity=_severity(payload.get("severity")),
        title=title.strip(),
        description=_text(payload.get("description")),
        exception_type=_text(payload.get("exception_type")),
        message=_text(payload.get("message")),
        stack_trace=_text(payload.get("stack_trace")),
        timestamp=last_seen,
        service=_text(payload.get("service")),
        raw=dict(payload),
    )
    fp = fingerprint(occurrence)
    return build_incident(
        occurrence=occurrence,
        fingerprint_value=fp.value,
        occurrences=_count(payload.get("occurrences")),
        first_seen=first_seen,
        last_seen=last_seen,
    )


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _severity(value: Any) -> Severity:
    if isinstance(value, str):
        try:
            return Severity(value.strip().lower())
        except ValueError:
            pass
    return Severity.ERROR


def _time(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return None


def _count(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1
