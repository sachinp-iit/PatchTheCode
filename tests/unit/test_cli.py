"""Operator surfaces: CLI commands that read the review and learning queues."""

from datetime import datetime

from patchthecode.cli import list_prs, rejections, status
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


def _seed(store: Store) -> None:
    ts = datetime.utcnow()
    incident = Incident(
        id="ops:1",
        fingerprint="fp-ops",
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={},
    )
    store.upsert_incident(incident)
    fix = FixProposal(
        location=CodeLocation(repository="acme/pay", file_path="src/svc.py"),
        diff="--- a/src/svc.py\n+++ b/src/svc.py\n-None\n+x",
        summary="guard the provider",
        related_files=["src/svc.py"],
    )
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