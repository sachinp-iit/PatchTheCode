"""Domain models shared across PatchTheCode modules.

These are the contracts that the agent core, integrations, and the LLM
gateway all speak. Changes here ripple through the whole codebase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from patchthecode.domain import Severity


class IncidentSource(BaseModel):
    """Where an incident came from on the observability side."""

    kind: str = Field(..., description='e.g. "logs", "errors", "traces", "alerts"')
    system: str = Field(..., description='e.g. "coralogix", "application_insights", "sentry"')


class Fingerprint(BaseModel):
    """Stable identity for a recurring problem across occurrences."""

    value: str = Field(..., description="sha256 of normalized exception identity")
    exception_type: str | None = None
    message: str | None = None
    stack_trace_hash: str | None = None


class Incident(BaseModel):
    """A single detected production problem."""

    id: str
    fingerprint: str
    source: IncidentSource
    severity: Severity
    title: str
    description: str | None = None
    first_seen: datetime
    last_seen: datetime
    occurrences: int = 1
    raw: dict[str, Any] = Field(default_factory=dict, description="normalized source payload")


class Evidence(BaseModel):
    """A piece of evidence collected during investigation."""

    kind: str = Field(..., description='e.g. "stack_trace", "log_batch", "deployment", "commit", "source"')
    source_system: str = Field(..., description='e.g. "coralogix", "github"')
    content: dict[str, Any]
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CodeLocation(BaseModel):
    """Resolved location of a problem in source control."""

    repository: str
    branch: str | None = None
    commit: str | None = None
    file_path: str | None = None
    function: str | None = None


class RootCause(BaseModel):
    """Final root-cause hypothesis for an incident."""

    location: CodeLocation
    explanation: str
    hypothesis: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)


class FixProposal(BaseModel):
    """A candidate code change plus the reasoning behind it."""

    location: CodeLocation
    diff: str
    summary: str
    root_cause: RootCause | None = None
    related_files: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Outcome of running one or more validation passes on a fix."""

    passed: bool
    checks: list[dict[str, Any]] = Field(default_factory=list, description="name, command, status, output_url")


class PullRequestData(BaseModel):
    """Metadata needed to open a PR on a git system."""

    repository: str
    title: str
    base_branch: str
    head_branch: str
    description: str
    diff: str


class PullRequestResult(BaseModel):
    """Result of opening a PR."""

    url: str
    number: int
    state: str = "open"


class InvestigationReport(BaseModel):
    """End-to-end output of the agent for one incident."""

    incident: Incident
    evidence: list[Evidence] = Field(default_factory=list)
    root_cause: RootCause | None = None
    fix: FixProposal | None = None
    validation: ValidationResult | None = None
    pull_request: PullRequestResult | None = None
    status: str = "investigated"
    created_at: datetime = Field(default_factory=datetime.utcnow)