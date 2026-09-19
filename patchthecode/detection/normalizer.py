"""Normalize raw occurrences from different observability systems.

Each integration feeds raw payloads here; PatchTheCode only reasons about
the normalized shape below.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from patchthecode.domain import Severity
from patchthecode.domain.models import Incident, IncidentSource


class NormalizedOccurrence:
    """A single normalized error/warning occurrence."""

    def __init__(
        self,
        *,
        system: str,
        kind: str,
        severity: Severity,
        title: str,
        description: str | None,
        exception_type: str | None,
        message: str | None,
        stack_trace: str | None,
        timestamp: datetime,
        service: str | None,
        raw: dict[str, Any],
    ) -> None:
        self.system = system
        self.kind = kind
        self.severity = severity
        self.title = title
        self.description = description
        self.exception_type = exception_type
        self.message = message
        self.stack_trace = stack_trace
        self.timestamp = timestamp
        self.service = service
        self.raw = raw


class OccurrenceNormalizer:
    """Base class for integration normalizers.

    Integrations implement ``normalize`` to convert their vendor payload
    (e.g. a Coralogix search hit) into a ``NormalizedOccurrence``.
    """

    def normalize(self, payload: dict[str, Any]) -> NormalizedOccurrence:
        raise NotImplementedError("implement in the integration module")


def build_incident(
    *,
    occurrence: NormalizedOccurrence,
    fingerprint_value: str,
    occurrences: int,
    first_seen: datetime,
    last_seen: datetime,
) -> Incident:
    source = IncidentSource(kind=occurrence.kind, system=occurrence.system)
    return Incident(
        id=f"{source.system}:{source.kind}:{fingerprint_value}",
        fingerprint=fingerprint_value,
        source=source,
        severity=occurrence.severity,
        title=occurrence.title,
        description=occurrence.description,
        first_seen=first_seen,
        last_seen=last_seen,
        occurrences=occurrences,
        raw={"service": occurrence.service, "exception_type": occurrence.exception_type},
    )