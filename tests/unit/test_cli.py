"""Operator surfaces: CLI commands that read the review and learning queues."""

import json
from datetime import datetime

from patchthecode.cli import list_prs, playbook, playbooks, rejections, status, watch
from patchthecode.domain import Severity
from patchthecode.domain.models import (
    CodeLocation,
    FixProposal,
    Incident,
    IncidentSource,
    InvestigationReport,
    PullRequestResult,
)
from patchthecode.storage.store import Store


class _StubStoreAgent:
    def __init__(self, store: Store) -> None:
        self.store = store


class _WatchStubAgent:
    """Agent stub for the watch command: records handles, no PRs."""

    def __init__(self) -> None:
        self.handled: list[str] = []

    async def handle(self, incident: Incident) -> InvestigationReport:
        self.handled.append(incident.id)
        return InvestigationReport(incident=incident, status="no_evidence")

    async def poll_pull_requests(self) -> list[dict]:
        return []


def _incident(incident_id: str = "ops:1", fingerprint: str = "fp-ops") -> Incident:
    ts = datetime.utcnow()
    return Incident(
        id=incident_id,
        fingerprint=fingerprint,
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={},
    )


def _seed(store: Store) -> None:
    incident = _incident()
    fix = FixProposal(
        location=CodeLocation(repository="acme/pay", file_path="src/svc.py"),
        diff="--- a/src/svc.py\n+++ b/src/svc.py\n-None\n+x",
        summary="guard the provider",
        related_files=["src/svc.py"],
    )
    store.upsert_incident(incident)
    store.save_report(InvestigationReport(incident=incident, status="pr_opened", fix=fix))
    store.save_pull_request(
        incident.id,
        "acme/pay",
        PullRequestResult(url="https://github.com/acme/pay/pull/9", number=9, state="open"),
    )


def _stub(monkeypatch, tmp_path) -> Store:
    store = Store(tmp_path / "ops.db")
    monkeypatch.setattr("patchthecode.cli._build_agent", lambda settings: _StubStoreAgent(store))
    return store


def test_list_prs_prints_review_queue(monkeypatch, tmp_path, capsys):
    store = _stub(monkeypatch, tmp_path)
    _seed(store)
    list_prs()
    out = capsys.readouterr().out
    assert "https://github.com/acme/pay/pull/9" in out
    assert "ops:1" in out
    assert "acme/pay" in out


def test_list_prs_reports_empty_queue(monkeypatch, tmp_path, capsys):
    _stub(monkeypatch, tmp_path)
    list_prs()
    assert "No open pull requests" in capsys.readouterr().out


def test_rejections_prints_learning_queue(monkeypatch, tmp_path, capsys):
    store = _stub(monkeypatch, tmp_path)
    _seed(store)
    store.mark_pull_request("ops:1", "closed")
    rejections()
    out = capsys.readouterr().out
    assert "fp-ops" in out
    assert "ops:1" in out
    assert "guard the provider" in out


def test_rejections_reports_empty_queue(monkeypatch, tmp_path, capsys):
    _stub(monkeypatch, tmp_path)
    rejections()
    assert "No rejected fixes recorded" in capsys.readouterr().out


def test_status_prints_totals(monkeypatch, tmp_path, capsys):
    store = _stub(monkeypatch, tmp_path)
    _seed(store)
    status()
    out = capsys.readouterr().out
    assert "incidents: 1" in out
    assert "open_prs: 1" in out


def test_playbooks_lists_fingerprints(monkeypatch, tmp_path, capsys):
    store = _stub(monkeypatch, tmp_path)
    _seed(store)
    playbooks()
    out = capsys.readouterr().out
    assert "fp-ops" in out
    assert "recurrences=1" in out


def test_playbooks_reports_empty(monkeypatch, tmp_path, capsys):
    _stub(monkeypatch, tmp_path)
    playbooks()
    assert "No playbooks yet" in capsys.readouterr().out


def test_playbook_shows_details(monkeypatch, tmp_path, capsys):
    store = _stub(monkeypatch, tmp_path)
    _seed(store)
    store.mark_pull_request("ops:1", "closed")
    playbook("fp-ops")
    out = capsys.readouterr().out
    assert "fingerprint: fp-ops" in out
    assert "recurrences: 1" in out
    assert "rejected (closed without merge): guard the provider" in out


def test_playbook_unknown_fingerprint(monkeypatch, tmp_path, capsys):
    _stub(monkeypatch, tmp_path)
    playbook("nope")
    assert "No playbook for nope" in capsys.readouterr().out


def test_watch_once_investigates_inbox(monkeypatch, tmp_path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.json").write_text(
        json.dumps(_incident("watch:1", "fp-watch").model_dump(mode="json")), encoding="utf-8"
    )
    agent = _WatchStubAgent()
    monkeypatch.setattr("patchthecode.cli._build_agent", lambda settings: agent)

    watch(inbox=inbox, interval=0, once=True, cycles=None, no_pr_poll=True)

    out = capsys.readouterr().out
    assert "watch:1" in out
    assert "no_evidence" in out
    assert "Watch finished 1 investigation(s)" in out
    assert agent.handled == ["watch:1"]
    assert (inbox / "processed" / "a.json").exists()


def test_watch_reports_empty_inbox(monkeypatch, tmp_path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr("patchthecode.cli._build_agent", lambda settings: _WatchStubAgent())

    watch(inbox=inbox, interval=0, once=True, cycles=None, no_pr_poll=True)
    assert "No new incidents found" in capsys.readouterr().out