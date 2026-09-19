"""Redact sensitive values from log/evidence payloads before they reach an LLM.

This is a safety gate: Coralogix / App Insights payloads routinely contain
tokens, cookies, and PII. Redaction must run before any LLM call and before
persisting evidence.
"""

from __future__ import annotations

import re
from typing import Any

_VALUES_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization|proxy-authorization|cookie)\s*[:=]\s*(?:bearer\s+)?\S+"),
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)(password|passwd|pwd|secret|token|api[-_]?key)\s*[:=]\s*\S+"),
    re.compile(r"\bhttps?://[^\s:@/]+:[^\s:@/]+@[^\s]+", re.IGNORECASE),  # url user:pass@host
    re.compile(r"\bPRIVATE KEY-----", re.IGNORECASE),
)

_MASK = "[REDACTED]"


def redact_text(text: str) -> str:
    result = text
    for pattern in _VALUES_PATTERNS:
        result = pattern.sub(_MASK, result)
    return result


def _redact_value(value: Any, path: str, field_globs: list[str]) -> Any:
    if isinstance(value, dict):
        return {k: _redact_value(v, f"{path}.{k}", field_globs) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v, path, field_globs) for v in value]
    if isinstance(value, str):
        masked = redact_text(value)
        if _field_matches(path, field_globs):
            return _MASK
        return masked
    return value


def _field_matches(path: str, globs: list[str]) -> bool:
    lowered = path.lower()
    for glob_ in globs:
        parts = glob_.lower().strip("*").split(".")
        if all(part in lowered for part in parts):
            return True
    return False


class Redactor:
    """Recursively redact secrets and sensitive fields in a nested payload."""

    def __init__(self, field_globs: list[str] | None = None) -> None:
        self.field_globs = field_globs or []

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {k: _redact_value(v, k, self.field_globs) for k, v in payload.items()}