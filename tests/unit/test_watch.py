"""Autonomous operation: the watch loop and the file-inbox incident feed."""

import json
from datetime import datetime
from pathlib import Path

from patchthecode.agent.sources import FileInbox
from patchthecode.agent.watch import WatchLoop
from patchthecode.domain import Severity
from patchthecode.domain.models import (
    Incident,
    IncidentSource,
    InvestigationReport,
)


def _incident(incident_id: str = "w:1", fingerprint: str = "fp-watch") -> Incident:
    ts = datetime.utcnow()
    return Incident(
        id=incident_id,
        fingerprint=fingerprint,
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={"service": "svc"},
    )


def _write(path: Path, incident: Incident) -> None:
    path.write_text(json.dumps(incident.model_dump(mode="json")), encoding="utf-8")


class _StubAgent:
    """Minimal stand-in for the Agent: records what it was asked to handle."""

    def __init__(self, fail_ids: set[str] | None = None, updates: list[dict] | None = None) -> None:
        self.handled: list[str] = []
        self.pr_polls = 0
        self.fail_ids = fail_ids or set()
        self.updates = updates if updates is not None else []

    async def handle(self, incident: Incident) -> InvestigationReport:
        if incident.id in self.fail_ids:
            raise RuntimeError("boom")
        self.handled.append(incident.id)
        return InvestigationReport(incident=incident, status="no_evidence")

    async def poll_pull_requests(self) -> list[dict]:
        self.pr_polls += 1
        return self.updates


class _ExplodingFeed:
    async def fetch(self) -> list[Incident]:
        raise RuntimeError("feed down")

    async def acknowledge(self, incident: Incident) -> None:
        return None


async def test_file_inbox_fetches_and_acknowledges(tmp_path):
    inbox = FileInbox(tmp_path / "inbox")
    inbox.directory.mkdir(parents=True)
    _write(inbox.directory / "a.json", _incident("a:1"))
    _write(inbox.directory / "b.json", _incident("b:1"))

    fetched = await inbox.fetch()
    assert [i.id for i in fetched] == ["a:1", "b:1"]

    await inbox.acknowledge(fetched[0])
    assert (inbox.processed_dir / "a.json").exists()
    assert not (inbox.directory / "a.json").exists()

    remaining = await inbox.fetch()
    assert [i.id for i in remaining] == ["b:1"]


async def test_file_inbox_tolerates_missing_directory_and_bad_json(tmp_path, caplog):
    inbox = FileInbox(tmp_path / "absent")
    assert await inbox.fetch() == []

    inbox.directory.mkdir(parents=True)
    (inbox.directory / "broken.json").write_text("{not json", encoding="utf-8")
    (inbox.directory / "wrong_shape.json").write_text('{"nope": 1}', encoding="utf-8")
    assert await inbox.fetch() == []
    # a second poll must not re-log the same broken files
    assert await inbox.fetch() == []


async def test_watch_loop_investigates_new_incidents_and_acknowledges(tmp_path):
    inbox = FileInbox(tmp_path / "inbox")
    inbox.directory.mkdir(parents=True)
    _write(inbox.directory / "a.json", _incident("a:1"))
    agent = _StubAgent()

    loop = WatchLoop(agent=agent, feed=inbox, max_cycles=1, poll_pull_requests=False)
    reports = await loop.run()

    assert [r.incident.id for r in reports] == ["a:1"]
    assert agent.handled == ["a:1"]
    assert (inbox.processed_dir / "a.json").exists()


async def test_watch_loop_keeps_going_after_a_bad_incident(tmp_path):
    inbox = FileInbox(tmp_path / "inbox")
    inbox.directory.mkdir(parents=True)
    _write(inbox.directory / "bad.json", _incident("bad:1"))
    _write(inbox.directory / "good.json", _incident("good:1"))
    agent = _StubAgent(fail_ids={"bad:1"})

    loop = WatchLoop(agent=agent, feed=inbox, max_cycles=1, poll_pull_requests=False)
    reports = await loop.run()

    assert agent.handled == ["good:1"]
    assert [r.incident.id for r in reports] == ["good:1"]
    # the failed incident is not acknowledged, so it is retried next cycle
    assert (inbox.directory / "bad.json").exists()


async def test_watch_loop_refreshes_pull_requests_each_cycle(tmp_path):
    inbox = FileInbox(tmp_path / "inbox")
    inbox.directory.mkdir(parents=True)
    agent = _StubAgent(updates=[{"incident_id": "a:1", "url": "u", "state": "merged"}])

    loop = WatchLoop(agent=agent, feed=inbox, max_cycles=2, interval_seconds=0)
    await loop.run()
    assert agent.pr_polls == 2


async def test_watch_loop_survives_feed_failure():
    agent = _StubAgent()
    loop = WatchLoop(agent=agent, feed=_ExplodingFeed(), max_cycles=1, poll_pull_requests=False)
    assert await loop.run() == []


async def test_watch_loop_sleeps_between_cycles_only(tmp_path):
    inbox = FileInbox(tmp_path / "inbox")
    inbox.directory.mkdir(parents=True)
    slept: list[float] = []

    async def _sleeper(seconds: float) -> None:
        slept.append(seconds)

    cycles: list[int] = []
    loop = WatchLoop(
        agent=_StubAgent(),
        feed=inbox,
        interval_seconds=7,
        max_cycles=3,
        poll_pull_requests=False,
        on_cycle=cycles.append,
        sleeper=_sleeper,
    )
    reports = await loop.run()

    assert cycles == [1, 2, 3]
    assert slept == [7, 7]
    assert reports == []
