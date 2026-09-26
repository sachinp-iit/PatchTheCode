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
) -> list[dict[str, str]]:
    """Form a root-cause hypothesis candidate for a fix."""
    user = (
        f"Determine the root cause for this incident.\n\n"
        f"INCIDENT:\n{incident}\n\n"
        f"EVIDENCE:\n{evidence}\n\n"
        f"SERVICE HINT: {service_hint or 'unknown'}\n\n"
        "Return JSON: {\"hypothesis\": str, \"confidence\": float, \"repository\": str, "
        "\"file_path\": str|None, \"function\": str|None, \"explanation\": str, "
        "\"evidence_refs\": [str]}"
    )
    return [{"role": "user", "content": user}]


def generate_fix_prompt(
    location: dict[str, Any],
    code_snippet: str,
    root_cause: str,
) -> list[dict[str, str]]:
    """Produce a candidate diff for a located root cause."""
    user = (
        f"Generate a minimal fix.\n\n"
        f"LOCATION:\n{location}\n\n"
        f"ROOT CAUSE:\n{root_cause}\n\n"
        f"CURRENT CODE:\n```\n{code_snippet}\n```\n\n"
        "Return JSON: {\"diff\": str, \"summary\": str, \"files\": [str]}"
    )
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