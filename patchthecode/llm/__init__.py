"""Model-agnostic LLM gateway and prompt templates."""

from patchthecode.llm.gateway import SYSTEM_PROMPT, GatewayOptions, LLMError, LLMGateway
from patchthecode.llm.prompts import (
    generate_fix_prompt,
    investigate_incident_prompt,
    review_fix_prompt,
    root_cause_prompt,
)

__all__ = [
    "GatewayOptions",
    "LLMError",
    "LLMGateway",
    "SYSTEM_PROMPT",
    "generate_fix_prompt",
    "investigate_incident_prompt",
    "review_fix_prompt",
    "root_cause_prompt",
]