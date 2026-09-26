"""Data-driven MCP tool-name alignment.

MCP servers expose tools under names that differ between vendors, versions,
and toolsets (GitHub's official server, `mcp-sentry`, a vendor GitLab server,
and so on). Instead of betting on a single name per action, every *system*
ships an ordered list of candidate names — first = preferred default — and the
running client resolves its tool map against the server's advertised
`list_tools()` output on first use. Explicit `tool_names` overrides always win.

`inspect-mcp` reports per connector which actions aligned with advertised
tools and which fell back, so operators can patch the maps to their server.
"""

from __future__ import annotations

from typing import TypedDict

ToolSpec = dict[str, list[str]]

TOOL_SPECS: dict[str, ToolSpec] = {
    "github": {
        "search_repositories": ["search_repositories"],
        "get_content": ["get_file_contents", "get_content"],
        "create_branch": ["create_branch", "create_or_update_file"],
        "create_commit": ["create_commit", "create_or_update_file", "push_files"],
        "create_pr": ["create_pull_request"],
        "get_pr": ["get_pull_request"],
    },
    "gitlab": {
        "search_repositories": ["search_projects", "search_repositories"],
        "get_content": ["get_file_contents", "get_content"],
        "create_branch": ["create_branch"],
        "create_commit": ["create_commit"],
        "create_pr": ["create_merge_request", "create_pull_request"],
        "get_pr": ["get_merge_request", "get_pull_request"],
    },
    "sentry": {
        "search_issues": ["search_issues", "list_issues", "get_list_issues"],
        "list_events": ["list_events", "list_issue_events"],
    },
    "coralogix": {
        "query_logs": ["query_logs", "search_logs", "query"],
        "list_deployments": ["list_deployments", "get_deployments"],
    },
    "appinsights": {
        "query": ["query", "run_query", "query_logs"],
        "list_exceptions": ["list_exceptions", "get_exceptions", "search_exceptions"],
    },
    "ci": {
        "create_check_run": ["create_check_run", "submit_check", "start_check"],
        "get_check_run": ["get_check_run", "poll_check", "get_check"],
    },
}


class ActionReport(TypedDict):
    action: str
    chosen: str
    status: str
    override: bool
    candidates: list[str]


class ToolReport(TypedDict):
    system: str
    total: int
    actions: list[ActionReport]


def tool_spec(system: str) -> ToolSpec:
    """The candidate tool map for a system; unknown systems get nothing."""
    return TOOL_SPECS.get(system.lower(), {})


def align_tools(system: str, advertised: list[str] | None, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Pick the concrete tool name per action.

    A caller-supplied override wins verbatim. Otherwise the first candidate
    the server advertises is used; when nothing is advertised the preferred
    (first) candidate is the fallback so behavior never silently changes.
    """
    spec = tool_spec(system)
    advertised_names = set(advertised or [])
    chosen: dict[str, str] = {}
    for action, candidates in spec.items():
        if overrides and action in overrides:
            chosen[action] = overrides[action]
            continue
        chosen[action] = next((c for c in candidates if c in advertised_names), candidates[0])
    return chosen


def report_for(system: str, advertised: list[str] | None, overrides: dict[str, str] | None = None) -> ToolReport:
    """Per-action alignment report used by `inspect-mcp`."""
    spec = tool_spec(system)
    advertised_names = set(advertised or [])
    chosen = align_tools(system, advertised, overrides)
    actions: list[ActionReport] = []
    for action, name in chosen.items():
        candidates = spec.get(action, [name])
        is_override = bool(overrides and action in overrides)
        actions.append(
            {
                "action": action,
                "chosen": name,
                "status": "aligned" if name in advertised_names else "fallback",
                "override": is_override,
                "candidates": candidates,
            }
        )
    return {"system": system, "total": len(actions), "actions": actions}