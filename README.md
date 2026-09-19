# MCP Server

A Python MCP server built with the official **MCP Python SDK / FastMCP
1.x**.\
The project exposes PostgreSQL, NLP/LLM, registry, and file capabilities
as MCP tools.

## Technology Stack

-   Python 3.13+
-   UV
-   MCP Python SDK `1.29.1`
-   FastMCP
-   FastAPI / Uvicorn (REST API layer)
-   LangChain + OpenAI
-   PostgreSQL / Neon
-   YAML-based tool and prompt configuration
-   ngrok (optional public reverse proxy)

------------------------------------------------------------------------

# 1. Installation

## Prerequisites

Install:

-   Python 3.13+
-   UV
-   An OpenAI API key if using the NLP tools
-   A PostgreSQL/Neon connection string if using PostgreSQL tools

Verify UV:

``` powershell
uv --version
```

## Create / sync the environment

From the project root:

``` powershell
uv sync
```

Run all Python commands through UV:

``` powershell
uv run python --version
```

The project is pinned to MCP 1.x because the code uses:

``` python
from mcp.server.fastmcp import FastMCP
```

The current verified MCP version is:

``` text
mcp 1.29.1
```

------------------------------------------------------------------------

# 2. Environment Configuration

Create or update `.env` in the project root.

Typical variables used by the project include:

``` env
OPENAI_API_KEY=your_openai_api_key
NEON_DB_URL=your_postgresql_connection_string
API_KEY=your_rest_api_key
TOOLS_YAML_PATH=C:\Users\<username>\mcp_server\config\tools.yaml
```

Do not commit real credentials to source control.

`env_loader.py` loads `.env` before the server initializes.

------------------------------------------------------------------------

# 3. Project Structure

``` text
mcp_server/
│
├── server.py
├── server_stdio.py
│
├── api.py
├── api_router.py
├── auto_router.py
├── auth.py
│
├── env_loader.py
├── logging_config.py
├── start_hidden.ps1
│
├── config/
│   ├── tools.yaml
│   ├── prompt_loader.py
│   └── prompts/
│       ├── agents.yaml
│       ├── core.yaml
│       ├── experiments.yaml
│       ├── nlp.yaml
│       ├── routing.yaml
│       ├── safety.yaml
│       └── tools.yaml
│
├── tools/
│   ├── __init__.py
│   ├── files.py
│   ├── nlp.py
│   ├── postgres.py
│   ├── registry.py
│   └── tool_registry.py
│
└── tests/
    └── test_prompts.py
```

The ZIP also contains runtime/logging artifacts and legacy Redis-related
files. Those are not part of the intended active MCP architecture.

------------------------------------------------------------------------

# 4. Purpose of Each File

## MCP Server

### `server.py`

**Production MCP HTTP/SSE entry point.**

Responsibilities:

1.  Load environment configuration.
2.  Create the FastMCP instance.
3.  Register PostgreSQL, NLP, registry, and file tools.
4.  Start FastMCP using SSE transport.

``` text
MCP Client
    ↓
SSE / HTTP
    ↓
server.py
    ↓
FastMCP
    ↓
tools/
```

Run it with:

``` powershell
uv run python server.py
```

The development server currently runs on:

``` text
http://127.0.0.1:9898
```

and the SSE endpoint is:

``` text
http://127.0.0.1:9898/sse
```

### `server_stdio.py`

**Development/debug MCP server for MCP Inspector.**

It registers the same FastMCP tools as `server.py`, but uses the default
stdio transport.

Run:

``` powershell
uv run python server_stdio.py
```

This is for local development/debugging, not the public HTTP deployment.

------------------------------------------------------------------------

# 5. Tools

The `tools/` directory contains the actual capabilities exposed through
FastMCP.

## `tools/postgres.py`

PostgreSQL capability.

MCP tools:

``` text
execute_sql
get_schema
```

Responsibilities:

-   Connect to PostgreSQL/Neon.
-   Execute SQL.
-   Retrieve public-schema metadata.
-   Apply the project's SQL validation before execution.

## `tools/nlp.py`

NLP/LLM capability.

MCP tools:

``` text
classify_intent
generate_sql
```

Uses:

-   LangChain
-   OpenAI
-   YAML prompt configuration

The prompt and model policies are loaded through `PromptRegistry`.

## `tools/registry.py`

Custom tool-intent resolution.

MCP tool:

``` text
resolve_tool_by_intent
```

It reads `TOOLS_YAML_PATH` and maps an intent/operation to a configured
tool name.

This is a **custom application registry**. It is separate from MCP's
native `tools/list` discovery mechanism.

## `tools/files.py`

File-system capability.

MCP tool:

``` text
list_files
```

Lists files in a specified directory.

## `tools/tool_registry.py`

Alternative/older registry implementation.

It overlaps with `tools/registry.py`. The active `server.py` imports
`registry.py`, so this file is not part of the primary MCP registration
path.

## `tools/__init__.py`

Marks `tools` as a Python package and supports imports such as:

``` python
from tools import postgres, nlp, registry, files
```

------------------------------------------------------------------------

# 6. FastAPI REST Layer

FastAPI is a separate HTTP/REST interface around selected Python tool
functions.

## `api.py`

Creates the FastAPI application:

``` text
api.py
  ↓
FastAPI()
  ↓
auto_router + api_router
```

Run with:

``` powershell
uv run uvicorn api:app --host 127.0.0.1 --port 5000
```

## `auto_router.py`

Automatically generates REST endpoints for selected tool functions.

Current mappings include:

``` text
POST /postgres/execute
POST /postgres/schema
POST /nlp/classify
POST /nlp/generate_sql
POST /registry/resolve
POST /files/list
```

It uses Python introspection and Pydantic `create_model()` to derive
request models from function signatures.

All routes in this router use the `require_api_key` dependency.

## `api_router.py`

Contains additional manually defined FastAPI routes.

It is separate from the dynamically generated routes in
`auto_router.py`.

## `auth.py`

Provides REST API-key authentication through the `X-API-Key` HTTP
header.

## `logging_config.py`

Configures rotating audit logging.

The audit log is written to:

``` text
audit.log
```

------------------------------------------------------------------------

# 7. Configuration

## `config/tools.yaml`

Defines the application's custom operation/tool registry.

Example:

``` yaml
tools:
  postgres_select:
    operation: SELECT
```

This configuration is consumed by the registry code.

## `config/prompt_loader.py`

Loads prompt definitions from the YAML prompt files.

## `config/prompts/*.yaml`

Stores prompt templates and model/policy configuration for different
application areas, including:

-   agents
-   core
-   experiments
-   NLP
-   routing
-   safety
-   tools

Keeping prompts in YAML allows prompt/configuration changes without
embedding all prompt text directly in Python code.

------------------------------------------------------------------------

# 8. Running the FastMCP Server

## HTTP/SSE server

Start:

``` powershell
uv run python server.py
```

Expected output:

``` text
Uvicorn running on http://127.0.0.1:9898
```

MCP SSE endpoint:

``` text
http://127.0.0.1:9898/sse
```

This is the server intended for HTTP-based MCP clients and development
through a reverse proxy such as ngrok.

------------------------------------------------------------------------

# 9. Verify the MCP Server

First verify the HTTP/SSE endpoint:

``` powershell
uv run python -c "import requests; r=requests.get('http://127.0.0.1:9898/sse', stream=True); print(r.status_code); print(r.headers.get('content-type'))"
```

Expected:

``` text
200
text/event-stream; charset=utf-8
```

A request to `/` returning `404 Not Found` is not a server failure; `/`
is not the MCP SSE endpoint.

------------------------------------------------------------------------

# 10. Verify MCP Tool Discovery

The server should expose:

``` text
execute_sql
get_schema
classify_intent
generate_sql
resolve_tool_by_intent
list_files
```

A simple MCP client test can connect to:

``` text
http://127.0.0.1:9898/sse
```

and call the MCP `tools/list` operation.

The important distinction is:

``` text
FastMCP
  ↓
MCP protocol
  ↓
tools/list
  ↓
registered MCP tools
```

No custom discovery mechanism is required for native MCP tool discovery.

------------------------------------------------------------------------

# 11. MCP Inspector Development Server

For local MCP Inspector debugging:

``` powershell
uv run python server_stdio.py
```

`server_stdio.py` is intentionally a development/debug entry point.

It uses stdio rather than SSE.

------------------------------------------------------------------------

# 12. ngrok

For exposing the HTTP server through ngrok:

1.  Start the FastMCP SSE server:

``` powershell
uv run python server.py
```

2.  In another terminal:

``` powershell
ngrok http 9898
```

Use the resulting public HTTPS URL together with the MCP SSE path:

``` text
https://<ngrok-domain>/sse
```

Do not expose an unauthenticated production MCP server publicly. Review
authentication and authorization at the MCP HTTP boundary before public
deployment.

------------------------------------------------------------------------

# 13. Tests

Run the test suite with:

``` powershell
uv run pytest
```

Run the prompt tests specifically:

``` powershell
uv run pytest tests/test_prompts.py
```

------------------------------------------------------------------------

# 14. Development Workflow

Recommended local workflow:

### Terminal 1 --- FastMCP

``` powershell
uv run python server.py
```

### Terminal 2 --- MCP/API testing

Use your MCP client or REST client against:

``` text
http://127.0.0.1:9898/sse
```

For REST testing, run:

``` powershell
uv run uvicorn api:app --host 127.0.0.1 --port 5000
```

### Optional --- public tunnel

``` powershell
ngrok http 9898
```

------------------------------------------------------------------------

# 15. Architecture Summary

``` text
                         MCP Client
                             │
                             │ MCP / SSE
                             ▼
                        server.py
                             │
                         FastMCP
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         postgres.py      nlp.py       registry.py
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                         files.py


                  Separate REST Interface
                             │
                             ▼
                           api.py
                             │
                 ┌───────────┴───────────┐
                 ▼                       ▼
           auto_router.py          api_router.py
                 │
                 ▼
          Python tool functions
```

## Core Principle

`server.py` is the **MCP composition and HTTP/SSE entry point**.

`server_stdio.py` is the **development/debug stdio entry point**.

`tools/` contains the **actual capabilities**.

`api.py`, `api_router.py`, and `auto_router.py` form a **separate REST
API layer**.

`config/` contains **tool and prompt configuration**.

`ngrok` is an optional **external reverse proxy/tunnel**, not part of
FastMCP itself.
