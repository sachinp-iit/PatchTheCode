"""Prompt templates for the agent's reasoning steps.

Keep prompts data-shaped and versioned here so behavior is reproducible
and diffable across model configurations.
"""

from __future__ import annotations

from typing import Any


def evidence_plan_prompt(
    incident: dict[str, Any],
    available_mcp: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Decide what evidence to collect and from which connectors."""
    user = (
        f"Plan the evidence collection for this production incident.\n\n"
        f"INCIDENT:\n{incident}\n\n"
        f"AVAILABLE MCP CONNECTORS (name + kind + tool names):\n{available_mcp}\n\n"
        "Return JSON {\"steps\": [{\"connector\": str, \"tool\": str, "
        "\"arguments\": dict, \"purpose\": str}]}. Use only the listed "
        "connector/tool names, request the narrowest time range and fields, "
        "and order by most discriminating evidence first."
    )
    return [{"role": "user", "content": user}]


def investigate_incident_prompt(incident: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Generate hypotheses and next investigation steps for an incident."""
    user = (
        f"Investigate this production incident.\n\n"
        f"INCIDENT:\n{incident}\n\n"
        f"AVAILABLE EVIDENCE:\n{evidence}\n\n"
        "Return JSON: {\"hypotheses\": [{\"description\": str, \"confidence\": float, "
        "\"next_evidence_to_collect\": str}], \"summary\": str}"
    )
    return [{"role": "user", "content": user}]


def root_cause_prompt(
    incident: dict[str, Any],
    evidence: list[dict[str, Any]],
    service_hint: str | None,
    history: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Form a root-cause hypothesis candidate for a fix.

    When the fingerprint has a debugging playbook, its known history is
    surfaced first so a recurring incident sharpens (rather than re-derives)
    the prior hypothesis.
    """
    user = (
        f"Determine the root cause for this incident.\n\n"
        f"INCIDENT:\n{incident}\n\n"
        f"EVIDENCE:\n{evidence}\n\n"
        f"SERVICE HINT: {service_hint or 'unknown'}\n\n"
    )
    if history:
        lines = []
        if history.get("recurrences", 0) > 1:
            lines.append(f"this fingerprint has recurred {history['recurrences']} time(s)")
        if history.get("last_title"):
            lines.append(f"last occurrence title: {history['last_title']}")
        merged = history.get("merged")
        if merged:
            lines.append(
                f"a previously accepted fix ({merged.get('pr', 'merged')}): {merged.get('summary', '')}"
            )
        for rejected in history.get("rejections") or []:
            lines.append(
                f"a rejected attempt ({rejected.get('reason', 'closed without merge')}): "
                f"{rejected.get('summary', '')}"
            )
        if lines:
            joined = "\n".join(f"  - {line}" for line in lines)
            user += f"KNOWN HISTORY FROM PREVIOUS ATTEMPTS:\n{joined}\n\n"
    user += (
        "Return JSON: {\"hypothesis\": str, \"confidence\": float, \"repository\": str, "
        "\"file_path\": str|None, \"function\": str|None, \"explanation\": str, "
        "\"evidence_refs\": [str]}"
    )
    return [{"role": "user", "content": user}]


def generate_fix_prompt(
    location: dict[str, Any],
    code_snippet: str,
    root_cause: str,
    rejections: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Produce a candidate diff for a located root cause.

    When reviewers have already closed a previous attempt for the same
    fingerprint, the rejected approach is surfaced so the model proposes
    something different instead of repeating it.
    """
    user = (
        f"Generate a minimal fix.\n\n"
        f"LOCATION:\n{location}\n\n"
        f"ROOT CAUSE:\n{root_cause}\n\n"
        f"CURRENT CODE:\n```\n{code_snippet}\n```\n\n"
    )
    if rejections:
        attempts = "\n".join(
            f"- reason: {rejected.get('reason', 'closed without merge')}\n"
            f"  summary: {rejected.get('summary', '')}\n"
            f"  diff:\n```diff\n{rejected.get('diff', '')}\n```"
            for rejected in rejections
        )
        user += (
            "A previous fix for this incident was rejected by a reviewer.\n"
            "Do not repeat the rejected approach; propose a different one.\n"
            f"PREVIOUSLY REJECTED FIXES:\n{attempts}\n\n"
        )
    user += "Return JSON: {\"diff\": str, \"summary\": str, \"files\": [str]}"
    return [{"role": "user", "content": user}]


def review_fix_prompt(diff: str, problems: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Critique a proposed diff before opening a PR."""
    user = (
        f"Review this proposed fix for correctness, safety, and regressions.\n\n"
        f"DIFF:\n{diff}\n\n"
        f"KNOWN PROBLEM CONTEXT:\n{problems}\n\n"
        "Return JSON: {\"verdict\": \"approve\"|\"request_changes\", \"issues\": [str]}"
    )
    return [{"role": "user", "content": user}]