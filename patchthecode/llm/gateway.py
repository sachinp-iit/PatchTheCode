"""Model-agnostic LLM gateway built on LiteLLM.

Each agent task (investigation, codegen, validation, summarize) maps to a
configured provider/model, so deployments can route expensive reasoning to
one model and cheap checks to another, and fail over if needed.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from patchthecode.config import ModelConfig

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are PatchTheCode, an AI Production Engineer. You investigate "
    "production incidents using evidence from observability and source control "
    "systems. You only act on evidence, never assume. You propose fixes as pull "
    "requests for human review."
)


class LLMError(RuntimeError):
    """Raised when an LLM call fails after retries are exhausted."""


class GatewayOptions(BaseModel):
    temperature: float = 0.2
    max_tokens: int = 4096
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMGateway:
    def __init__(self, configs: list[ModelConfig], timeout_seconds: int = 120) -> None:
        self._models: dict[str, str] = {}
        for cfg in configs:
            self._models[cfg.task] = cfg.model
        self._timeout = timeout_seconds

    def model_for(self, task: str) -> str:
        return self._models.get(task) or self._models.get("investigation", "")

    async def complete(
        self,
        task: str,
        messages: list[dict[str, str]],
        options: GatewayOptions | None = None,
    ) -> str:
        """Run an async completion against the model configured for `task`."""
        model = self.model_for(task)
        if not model:
            raise LLMError(f"no model configured for task {task!r}")
        opts = options or GatewayOptions()
        from litellm import acompletion

        try:
            response = await acompletion(
                model=model,
                messages=messages,
                temperature=opts.temperature,
                max_tokens=opts.max_tokens,
                timeout=self._timeout,
                metadata=opts.metadata,
            )
        except Exception as exc:  # noqa: BLE001 - LiteLLM raises provider-specific errors
            raise LLMError(f"LLM call failed for task {task!r}: {exc}") from exc
        content = response.choices[0].message.content
        if not content:
            raise LLMError(f"empty LLM response for task {task!r}")
        return content

    async def complete_json(
        self,
        task: str,
        messages: list[dict[str, str]],
        options: GatewayOptions | None = None,
    ) -> dict[str, Any]:
        """Ask for a JSON object and parse it.

        TODO: move to structured output / tool-calling when the router plans that.
        """
        import json

        wrapped = [
            {"role": "system", "content": SYSTEM_PROMPT + " Respond with a single JSON object only."},
            *messages,
        ]
        raw = await self.complete(task, wrapped, options)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM did not return valid JSON for task {task!r}") from exc
        if not isinstance(data, dict):
            raise LLMError(f"LLM returned non-object JSON for task {task!r}")
        return data