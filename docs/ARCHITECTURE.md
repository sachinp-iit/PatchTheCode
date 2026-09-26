# PatchTheCode Architecture

> Working skeleton. Every module below is a contract you can extend; where the
> real behavior is not wired yet it raises or returns a placeholder with a
> `TODO` marker pointing at the intended implementation.

## Technology

- **Python 3.11+** package (`patchthecode/`)
- **MCP** (official `mcp` Python SDK) is the *only* integration boundary to
  external systems: observability, git, CI, communication, validation
- **LiteLLM** gateway for a model-agnostic LLM layer with per-task routing
- **Pydantic** models as the shared domain contract
- **SQLite** (`data/patchthecode.db`) for dedup + investigation history
- **Typer** CLI; **pytest** for tests

## Repository layout

```text
patchthecode/
├── agent/             Agent core (orchestrator)
├── detection/         normalization + fingerprinting
├── investigation/     evidence collection
├── repository/        incident -> repo/file resolution
├── remediation/       fix proposal
├── validation/        validate a fix
├── mcp/               MCP client wrapper, redaction, registry
├── integrations/      vendor adapters (coralogix/, github/, ...)
├── llm/               LiteLLM gateway + prompts
├── notifications/     Slack/Teams/log notifiers
├── storage/           SQLite store (dedup + history)
├── domain/            shared Pydantic models
├── cli.py             entry point
├── config.py          settings (.env based)
├── docs/
│   └── ARCHITECTURE.md
├── config/
│   └── mcp.example.json
├── examples/
│   └── incident.*.json
└── tests/
    ├── unit/
    └── integration/
```

## Vertical slice you can run today

```text
                ┌──────────────┐
                │ CLI: replay/ │
                │     demo     │
                └──────┬───────┘
                       ▼
                ┌──────────────┐          ┌─────────────┐
                │    Agent     │─────────▶│  Store      │
                │  (orchestr.) │          │  (dedup)    │
                └──────┬───────┘          └─────────────┘
                       │
        ┌──────────────┼───────────────────┐
        ▼              ▼                   ▼
 Evidence       Repository            Notifiers
 Collector      Discovery             (log/slack)
        │              │                   │
        └── MCP client wrapper (registry) ─┘
                │
        ┌───────┴────────┐
        ▼                ▼
 Coralogix MCP     GitHub MCP
 (query_logs,      (search_repo,
  deployments)      file resolve,
                    PR create*)
```

Steps wired so far:

1. **detection** → `Incident` model (normalized payload)
2. **dedup** via fingerprint in the SQLite `Store`
3. **evidence** via the evidence plan against configured connectors
4. **repo discovery** (stub: returns service name as repository)
5. **root cause / fix / validation / PR** → placeholders with TODOs

## Model-agnostic LLM layer

`llm/gateway.py` maps **task → model**:

| Task           | Env                                   |
|----------------|---------------------------------------|
| investigation  | `PATCHTHECODE_MODEL_INVESTIGATION`    |
| codegen        | `PATCHTHECODE_MODEL_CODEGEN`          |
| validation     | `PATCHTHECODE_MODEL_VALIDATION`       |
| default        | `PATCHTHECODE_MODEL_DEFAULT`          |

Any provider LiteLLM supports (OpenAI, Anthropic, OpenRouter, Gemini, ...) with
the corresponding API key in `.env`. Custom JSON-output parsing lives in
`LLMGateway.complete_json`.

## MCP connections

`config/mcp.example.json` → copy to `config/mcp.json`, set
`PATCHTHECODE_MCP_CONFIG` in `.env`.

Each connection is:

```json
{
  "name": "coralogix_mcp",
  "kind": "observability",        // observability | git | ci | validation | communication
  "transport": "stdio",           // "stdio" | "streamable-http"
  "command": "npx",
  "args": ["-y", "@coralogix/mcp-server"],
  "env": {},
  "url": ""                       // required for streamable-http
}
```

`kind` groups connectors so the agent can request "all observability
connectors" without hard-coding names (`ConnectorRegistry.by_kind`).

**Start here:** run `patchthecode inspect-mcp` with a real Coralogix / GitHub
MCP server and note the actual tool names (module TODOs assume
`query_logs`, `list_deployments`, `search_repositories`, `get_content`).

## Redaction (must-happen-before-LLM)

`mcp/redaction.py` masks secrets in evidence **before** any LLM call or store
write:

- regex patterns for `Authorization`, cookies, passwords, URLs with creds, keys
- configured field globs via `PATCHTHECODE_REDACT_FIELDS`

All evidence goes through `EvidenceCollector` (redaction-clean) → agent →
prompts. Do not bypass this path.

## Safety model

- Investigation = **read-only** on production systems
- The only write path is `GitHubClient.open_pull_request`, which currently
  raises `NotImplementedError` until the branch/commit/PR flow behind the
  human-review gate is implemented
- Fixes always land as a PR for human review; no silent production changes

## Where to build next (priority)

1. **MCP tool names**: run `inspect-mcp` against real Coralogix / Sentry /
   App Insights / GitHub / GitLab MCP servers; align the default tool-name
   maps in each `integrations/*/client.py`.
2. **Learning loop**: track PR merged/closed in the Store; replay accepted
   fixes in tests.

Done:
- Evidence planner (LLM-driven, `investigation/planner.py`).
- Root-cause + fix flow (`analyzer.py`, `remediation/fixer.py`).
- Git write path (`remediation/patch.py` + `open_pull_request`) behind the
  approval gate (`security/approver.py`; opt in via `PATCHTHECODE_AUTO_PR`).
- Pluggable adapters: Sentry, Application Insights, and GitLab clients plus
  `integrations.factory.adapter_for` — selection is by MCP `kind` + optional
  `system` hint, never by connector name.

## Test / lint

```bash
pip install -e ".[dev]"
pytest
ruff check patchthecode tests
```