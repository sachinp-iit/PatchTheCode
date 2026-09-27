"""Render notification payloads for chat channels.

Kept free of transport concerns so a summary reads the same on Slack,
Teams, or the console.
"""

from __future__ import annotations

from patchthecode.domain.models import InvestigationReport


def render_summary(report: InvestigationReport) -> str:
    """A compact Markdown summary of a finished investigation."""
    incident = report.incident
    root_cause = report.root_cause
    fix = report.fix
    validation = report.validation
    pr = report.pull_request
    lines = [
        f"*[PatchTheCode] {incident.title}*",
        f"status: `{report.status}` | severity: `{incident.severity.value}` | incident `{incident.id}`",
        f"fingerprint: `{incident.fingerprint}` | occurrences: {incident.occurrences}",
    ]
    if root_cause is not None:
        lines.append(f"root cause: {root_cause.hypothesis}")
        location = root_cause.location
        path = f"{location.repository}/{location.file_path}" if location.file_path else location.repository
        if path:
            lines.append(f"location: `{path}`")
    if fix is not None and fix.diff:
        lines.append(f"fix: {fix.summary}")
    if validation is not None:
        lines.append(f"validation: {'passed' if validation.passed else 'failed'}")
    if pr is not None and pr.url:
        lines.append(f"PR: {pr.url}")
    return "\n".join(lines)


def render_review_request(report: InvestigationReport) -> str:
    """A prompt asking a human to review the proposed change."""
    incident = report.incident
    root_cause = report.root_cause
    fix = report.fix
    head = f"patchthecode/{incident.id.replace('/', '-')[-20:]}"
    lines = [
        f"[PatchTheCode] Please review the proposed fix for `{incident.title}`.",
        f"incident: `{incident.id}` | status: `{report.status}`",
    ]
    if root_cause is not None:
        lines.append(f"repository: `{root_cause.location.repository}`")
    if fix is not None and fix.diff:
        lines.append(f"summary: {fix.summary}")
    pr = report.pull_request
    if pr is not None and pr.url:
        lines.append(f"open PR: {pr.url}")
    else:
        lines.append(f"diff staged on branch `{head}` — approval will open the pull request")
    return "\n".join(lines)


def render_approval_request(
    action: str,
    payload: dict,
    code: str,
    timeout_seconds: int = 300,
) -> str:
    """A chat prompt asking a human to approve/reject one write action.

    Embeds a correlation ``code`` the reviewer can quote; the interactive
    approver matches replies or reactions that carry it.
    """
    lines = [
        f"[PatchTheCode] Approval required for `{action}`.",
        f"request: `{code}`",
    ]
    for key in ("repository", "head_branch", "base_branch"):
        value = payload.get(key)
        if value:
            lines.append(f"{key}: `{value}`")
    files = payload.get("files")
    if files:
        lines.append(f"files: {', '.join(str(f) for f in files)}")
    lines.append(f"Reply \u2705 `approve` or \u274c `reject` within {timeout_seconds} seconds.")
    return "\n".join(lines)