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