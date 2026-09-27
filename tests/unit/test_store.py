from datetime import datetime

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


def _incident(fingerprint: str = "fp-1") -> Incident:
    ts = datetime.utcnow()
    return Incident(
        id="t:store:1",
        fingerprint=fingerprint,
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={"service": "svc"},
    )


def _fix() -> FixProposal:
    return FixProposal(
        location=CodeLocation(repository="acme/pay", file_path="src/svc.py"),
        diff="--- a/src/svc.py\n+++ b/src/svc.py\n@@ -1 +1 @@\n-None\n+x",
        summary="guard the provider",
        related_files=["src/svc.py"],
    )


def test_store_round_trips_pull_request(tmp_path):
    store = Store(tmp_path / "s.db")
    incident = _incident()
    store.upsert_incident(incident)
    report = InvestigationReport(incident=incident, status="pr_opened", fix=_fix())
    store.save_report(report)

    pr = PullRequestResult(url="https://github.com/acme/pay/pull/3", number=3, state="open")
    store.save_pull_request(incident.id, "acme/pay", pr)

    open_prs = store.open_pull_requests()
    assert len(open_prs) == 1
    assert open_prs[0]["incident_id"] == incident.id
    assert open_prs[0]["repository"] == "acme/pay"
    assert open_prs[0]["pr"].number == 3

    store.mark_pull_request(incident.id, "merged")
    assert store.open_pull_requests() == []


def test_store_known_fix_after_merge(tmp_path):
    store = Store(tmp_path / "s.db")
    incident = _incident(fingerprint="fp-learn")
    incident.id = "t:store:1"
    store.upsert_incident(incident)
    report = InvestigationReport(incident=incident, status="pr_opened", fix=_fix())
    store.save_report(report)
    store.save_pull_request(
        incident.id,
        "acme/pay",
        PullRequestResult(url="https://github.com/acme/pay/pull/3", number=3, state="open"),
    )

    stored_incident = store.get_incident("t:store:1")
    assert stored_incident is not None
    assert store.known_fix("fp-learn") is None  # not yet merged

    store.mark_pull_request(incident.id, "merged")
    known = store.known_fix("fp-learn")
    assert known is not None
    fix, pr = known
    assert fix.summary == "guard the provider"
    assert pr.url == "https://github.com/acme/pay/pull/3"
    assert pr.state == "merged"


def test_store_known_fix_ignores_closed_prs(tmp_path):
    store = Store(tmp_path / "s.db")
    incident = _incident(fingerprint="fp-closed")
    store.upsert_incident(incident)
    report = InvestigationReport(incident=incident, status="pr_opened", fix=_fix())
    store.save_report(report)
    store.save_pull_request(
        incident.id,
        "acme/pay",
        PullRequestResult(url="https://github.com/acme/pay/pull/4", number=4, state="open"),
    )
    store.mark_pull_request(incident.id, "closed")
    assert store.known_fix("fp-closed") is None


def test_store_records_rejection_when_pr_closed_without_merge(tmp_path):
    store = Store(tmp_path / "s.db")
    incident = _incident(fingerprint="fp-rej")
    store.upsert_incident(incident)
    report = InvestigationReport(incident=incident, status="pr_opened", fix=_fix())
    store.save_report(report)
    store.save_pull_request(
        incident.id,
        "acme/pay",
        PullRequestResult(url="https://github.com/acme/pay/pull/5", number=5, state="open"),
    )

    assert store.has_rejections("fp-rej") is False
    store.mark_pull_request(incident.id, "closed")
    store.mark_pull_request(incident.id, "closed")  # idempotent
    assert store.has_rejections("fp-rej") is True
    rejected = store.rejected_fixes("fp-rej")
    assert len(rejected) == 1
    assert rejected[0]["summary"] == "guard the provider"
    assert "--- a/src/svc.py" in rejected[0]["diff"]
    assert rejected[0]["reason"] == "closed without merge"
    assert store.known_fix("fp-rej") is None


def test_store_merge_does_not_record_rejection(tmp_path):
    store = Store(tmp_path / "s.db")
    incident = _incident(fingerprint="fp-merge-ok")
    store.upsert_incident(incident)
    store.save_report(InvestigationReport(incident=incident, status="pr_opened", fix=_fix()))
    store.save_pull_request(
        incident.id,
        "acme/pay",
        PullRequestResult(url="https://github.com/acme/pay/pull/6", number=6, state="open"),
    )
    store.mark_pull_request(incident.id, "merged")
    assert store.has_rejections("fp-merge-ok") is False


def test_store_all_rejections_and_summary(tmp_path):
    store = Store(tmp_path / "s.db")
    incident = _incident(fingerprint="fp-all")
    store.upsert_incident(incident)
    store.save_report(InvestigationReport(incident=incident, status="pr_opened", fix=_fix()))
    store.save_pull_request(
        incident.id,
        "acme/pay",
        PullRequestResult(url="https://github.com/acme/pay/pull/7", number=7, state="open"),
    )

    assert store.summary()["open_prs"] == 1
    store.mark_pull_request(incident.id, "closed")

    rows = store.all_rejections()
    assert len(rows) == 1
    assert rows[0]["fingerprint"] == "fp-all"
    assert rows[0]["incident_id"] == incident.id
    assert rows[0]["summary"] == "guard the provider"

    counts = store.summary()
    assert counts["incidents"] == 1
    assert counts["investigations"] == 1
    assert counts["open_prs"] == 0
    assert counts["merged_fixes"] == 0
    assert counts["rejections"] == 1


def test_store_playbook_unknown_fingerprint(tmp_path):
    store = Store(tmp_path / "s.db")
    assert store.playbook("nope") is None
    assert store.playbooks() == []


def test_store_playbook_compiles_history(tmp_path):
    store = Store(tmp_path / "s.db")
    incident = _incident(fingerprint="fp-book")
    store.upsert_incident(incident)
    store.save_report(InvestigationReport(incident=incident, status="pr_opened", fix=_fix()))
    store.save_pull_request(
        incident.id,
        "acme/pay",
        PullRequestResult(url="https://github.com/acme/pay/pull/8", number=8, state="open"),
    )
    store.mark_pull_request(incident.id, "closed")

    book = store.playbook("fp-book")
    assert book is not None
    assert book["recurrences"] == 1
    assert book["last_title"] == "boom"
    assert book["merged"] is None
    assert len(book["rejections"]) == 1
    assert book["rejections"][0]["summary"] == "guard the provider"

    books = store.playbooks()
    assert len(books) == 1
    assert books[0]["fingerprint"] == "fp-book"


def test_store_playbook_includes_merged_fix(tmp_path):
    store = Store(tmp_path / "s.db")
    incident = _incident(fingerprint="fp-book-merged")
    store.upsert_incident(incident)
    store.save_report(InvestigationReport(incident=incident, status="pr_merged", fix=_fix()))
    store.save_pull_request(
        incident.id,
        "acme/pay",
        PullRequestResult(url="https://github.com/acme/pay/pull/9", number=9, state="merged"),
    )

    book = store.playbook("fp-book-merged")
    assert book is not None
    assert book["merged"] == {
        "summary": "guard the provider",
        "diff": _fix().diff,
        "pr": "https://github.com/acme/pay/pull/9",
    }
    assert book["rejections"] == []