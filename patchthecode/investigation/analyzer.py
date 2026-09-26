"""Root-cause analysis from collected evidence via the LLM.

Turns the evidence gathered for an incident into a RootCause hypothesis with
a resolved code location. When no evidence exists, the model is unreachable,
or the response is malformed, it returns an explicit low-confidence "need
more evidence" result instead of guessing.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from patchthecode.domain.models import CodeLocation, Evidence, Incident, RootCause
from patchthecode.llm.gateway import LLMGateway
from patchthecode.llm.prompts import root_cause_prompt

logger = logging.getLogger(__name__)

INSUFFICIENT_HYPOTHESIS = "Insufficient evidence to form a root cause"


class RootCauseAnalyzer:
    """Form a root-cause hypothesis for an incident from its evidence."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    async def analyze(self, incident: Incident, evidence: list[Evidence]) -> RootCause:
        if not evidence:
            logger.info("no evidence for %s; returning insufficient-evidence result", incident.id)
            return self.insufficient(incident, reason="No evidence was collected for this incident.")
        service = (incident.raw.get("service") or None) if incident.raw else None
        messages = root_cause_prompt(
            incident.model_dump(mode="json"),
            [e.model_dump(mode="json") for e in evidence],
            service,
        )
        try:
            data = await self.gateway.complete_json("investigation", messages)
        except Exception:  # noqa: BLE001 - never let a failing model produce a wrong answer
            logger.warning("root-cause analysis failed for %s; returning insufficient-evidence result", incident.id, exc_info=True)
            return self.insufficient(incident, reason="The reasoning model was unavailable.")
        try:
            return self._parse(data)
        except (ValueError, TypeError, ValidationError):  # noqa: PERF203
            logger.warning("root-cause analysis returned an invalid shape for %s", incident.id, exc_info=True)
            return self.insufficient(incident, reason="The model returned an invalid root cause.")

    def insufficient(self, incident: Incident, reason: str) -> RootCause:
        return RootCause(
            location=CodeLocation(repository="unknown"),
            hypothesis=INSUFFICIENT_HYPOTHESIS,
            explanation=reason,
            confidence=0.0,
        )

    def _parse(self, data: dict[str, Any]) -> RootCause:
        confidence = float(data.get("confidence") or 0.0)
        confidence = max(0.0, min(1.0, confidence))
        repository = str(data.get("repository") or "unknown")
        location = CodeLocation(
            repository=repository,
            branch=data.get("branch"),
            commit=data.get("commit"),
            file_path=data.get("file_path"),
            function=data.get("function"),
        )
        return RootCause(
            location=location,
            explanation=str(data.get("explanation") or ""),
            hypothesis=str(data.get("hypothesis") or INSUFFICIENT_HYPOTHESIS),
            confidence=confidence,
            evidence_refs=list(data.get("evidence_refs") or []),
        )