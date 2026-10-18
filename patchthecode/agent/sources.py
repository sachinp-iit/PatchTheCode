"""Incident feeds for autonomous operation.

A feed yields incidents to investigate and acknowledges them once the agent has
taken them, so a long-running watch loop can be driven by whatever alerting
system the team already uses. `FileInbox` is the zero-credential default:
alerting drops incident JSON files into a directory and the loop picks them up.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from patchthecode.domain.models import Incident

logger = logging.getLogger(__name__)


@runtime_checkable
class IncidentFeed(Protocol):
    """Where new incidents come from in autonomous mode."""

    async def fetch(self) -> list[Incident]:
        """Return the incidents waiting to be investigated."""

    async def acknowledge(self, incident: Incident) -> None:
        """Mark an incident as taken, so it is not handed out again."""


class FileInbox:
    """An incident feed backed by a directory of JSON payloads.

    Each `*.json` file in the inbox is an `Incident`. Unreadable files are
    retried on the next poll (a half-written file usually becomes valid) but
    only logged once; acknowledged files move to `processed/` so the same
    incident is never re-investigated.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.processed_dir = directory / "processed"
        self._pending: dict[str, Path] = {}
        self._deferred: set[str] = set()

    async def fetch(self) -> list[Incident]:
        incidents: list[Incident] = []
        for path in self._files():
            try:
                incident = Incident.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError) as exc:
                if path.name not in self._deferred:
                    self._deferred.add(path.name)
                    logger.warning("skipping unreadable incident file %s: %s", path.name, exc)
                continue
            self._deferred.discard(path.name)
            self._pending[incident.id] = path
            incidents.append(incident)
        return incidents

    async def acknowledge(self, incident: Incident) -> None:
        path = self._pending.pop(incident.id, None)
        if path is None or not path.exists():
            return
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        path.replace(self.processed_dir / path.name)

    def _files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(p for p in self.directory.glob("*.json") if p.is_file())


class QueueFeed:
    """In-memory incident feed for pushed alerts (webhooks).

    `fetch` drains the queue, so an acknowledged incident is just a no-op;
    re-delivery is still deduplicated by the store if a cycle crashes before
    the investigation is saved.
    """

    def __init__(self) -> None:
        self._queue: list[Incident] = []

    def push(self, incident: Incident) -> int:
        """Queue an incident; returns how many are waiting."""
        self._queue.append(incident)
        return len(self._queue)

    async def fetch(self) -> list[Incident]:
        pending, self._queue = self._queue, []
        return pending

    async def acknowledge(self, incident: Incident) -> None:
        return None  # fetch already removed it


class CompositeFeed:
    """Fan in multiple feeds, routing each incident's ack back to its origin.

    A failing feed does not hide incidents from the healthy ones.
    """

    def __init__(self, feeds: list[IncidentFeed]) -> None:
        self._feeds = list(feeds)
        self._owners: dict[str, IncidentFeed] = {}

    async def fetch(self) -> list[Incident]:
        incidents: list[Incident] = []
        for feed in self._feeds:
            try:
                fetched = await feed.fetch()
            except Exception:  # noqa: BLE001 - one broken feed must not starve the loop
                logger.exception("incident feed failed to list incidents")
                continue
            for incident in fetched:
                self._owners[incident.id] = feed
                incidents.append(incident)
        return incidents

    async def acknowledge(self, incident: Incident) -> None:
        feed = self._owners.pop(incident.id, None)
        if feed is not None:
            await feed.acknowledge(incident)
