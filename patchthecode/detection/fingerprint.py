"""Fingerprint occurrences so the same problem is not re-investigated.

The fingerprint is derived from the stable identity of the problem:
exception type + message + normalized stack-trace frames. Dynamic values
(ids, timestamps, numbers) are stripped before hashing.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from patchthecode.detection.normalizer import NormalizedOccurrence
from patchthecode.domain.models import Fingerprint


def _strip_noise(text: str) -> str:
    """Remove dynamic tokens that vary between occurrences of one bug."""
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", text)  # hex ids
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}[Tt]\S+\b", "<ts>", text)  # timestamps
    text = re.sub(r"\d+", "<n>", text)  # numbers
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def stack_frames(stack_trace: str | None, max_frames: int = 12) -> list[str]:
    """Extract canonical class.method names, dropping line numbers."""
    if not stack_trace:
        return []
    frames: list[str] = []
    for line in stack_trace.splitlines():
        stripped = line.strip()
        call = re.search(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s*\(", line)
        if call:
            frames.append(f"{call.group(1)}.{call.group(2)}")
        elif stripped.startswith(("at", "com.", "org.", "io.", "net.")):
            frames.append(_strip_noise(stripped))
    return frames[:max_frames]


def fingerprint(occurrence: NormalizedOccurrence, max_frames: int = 12) -> Fingerprint:
    """Build a stable fingerprint for an occurrence."""
    message = _strip_noise(occurrence.message or occurrence.title) if occurrence.message else None
    frames = stack_frames(occurrence.stack_trace, max_frames=max_frames)
    stack_hash = None
    if frames:
        stack_hash = hashlib.sha256("|".join(frames).encode("utf-8")).hexdigest()[:16]
    identity = "|".join(
        part for part in [occurrence.exception_type or "", message or "", stack_hash or ""] if part
    )
    value = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return Fingerprint(value=value, exception_type=occurrence.exception_type, message=message, stack_trace_hash=stack_hash)


def fingerprint_payload(payload: dict[str, Any]) -> str:
    """Hash an arbitrary occurrence payload for tests/mocks."""
    return hashlib.sha256(str(payload).encode("utf-8")).hexdigest()