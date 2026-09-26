"""Configuration loading from environment / .env via pydantic-settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelConfig(BaseModel):
    """A model assignment for one agent task."""

    task: str = Field(..., description='one of: investigation, codegen, validation, summarize')
    model: str = Field(..., description="LiteLLM provider/model string, e.g. openrouter/anthropic/claude-sonnet")


class MCPConnection(BaseModel):
    """Describe how to reach one MCP server."""

    name: str
    kind: str = Field(..., description='one of: observability, git, ci, communication, validation')
    system: str | None = Field(
        default=None,
        description="vendor hint for adapter selection: coralogix, appinsights, sentry, github, gitlab, ...",
    )
    transport: str = Field(default="stdio", description='"stdio" or "streamable-http"')
    command: str | None = None  # stdio transport: executable
    args: list[str] = Field(default_factory=list)  # stdio transport: args
    url: str | None = None  # streamable-http transport
    env: dict[str, str] = Field(default_factory=dict)  # extra env for the server process


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    model_default: str = Field(default="", alias="PATCHTHECODE_MODEL_DEFAULT")
    model_investigation: str | None = Field(default=None, alias="PATCHTHECODE_MODEL_INVESTIGATION")
    model_codegen: str | None = Field(default=None, alias="PATCHTHECODE_MODEL_CODEGEN")
    model_validation: str | None = Field(default=None, alias="PATCHTHECODE_MODEL_VALIDATION")
    llm_timeout_seconds: int = Field(default=120, alias="PATCHTHECODE_LLM_TIMEOUT_SECONDS")

    auto_pr: bool = Field(default=False, alias="PATCHTHECODE_AUTO_PR")

    mcp_config: Path | None = Field(default=None, alias="PATCHTHECODE_MCP_CONFIG")
    store_path: Path = Field(default=Path("data/patchthecode.db"), alias="PATCHTHECODE_STORE_PATH")

    slack_webhook_url: str | None = Field(default=None, alias="PATCHTHECODE_SLACK_WEBHOOK_URL")
    teams_webhook_url: str | None = Field(default=None, alias="PATCHTHECODE_TEAMS_WEBHOOK_URL")

    redact_fields: str = Field(
        default="Authorization,Cookie,password,secret,token,api_key",
        alias="PATCHTHECODE_REDACT_FIELDS",
    )

    def model_configs(self) -> list[ModelConfig]:
        configs = [
            ModelConfig(task="investigation", model=self.model_investigation or self.model_default),
            ModelConfig(task="codegen", model=self.model_codegen or self.model_default),
            ModelConfig(task="validation", model=self.model_validation or self.model_default),
        ]
        return configs

    def mcp_connections(self) -> list[MCPConnection]:
        if self.mcp_config is None:
            return []
        raw: list[dict[str, Any]] = json.loads(Path(self.mcp_config).read_text(encoding="utf-8"))
        return [MCPConnection.model_validate(item) for item in raw]

    def redact_field_glob(self) -> list[str]:
        return [f.strip() for f in self.redact_fields.split(",") if f.strip()]