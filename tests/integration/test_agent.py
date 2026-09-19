from datetime import datetime

import pytest

from patchthecode.agent.orchestrator import Agent
from patchthecode.domain import Severity
from patchthecode.domain.models import Incident, IncidentSource
from patchthecode.llm.gateway import LLMGateway
from patchthecode.notifications.notifier import LogNotifier
from patchthecode.storage.store import Store


@pytest.fixture()
def agent(tmp_path):
    gateway = LLMGateway([], timeout_seconds=5)
    store = Store(tmp_path / "test.db")
    return Agent(gateway=gateway, store=store, notifiers=[LogNotifier()])


def _incident() -> Incident:
    ts = datetime.utcnow()
    return Incident(
        id="t:x:1",
        fingerprint="fp-1",
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={"service": "svc"},
    )


async def test_agent_short_circuits_duplicates(agent):
    first = await agent.handle(_incident())
    assert first.status == "no_evidence"
    second = await agent.handle(_incident())
    assert second.status == "duplicate"


async def test_agent_upserts_occurrence_counts(agent):
    one = _incident()
    agent.store.upsert_incident(one)
    repeat = _incident()
    repeat.occurrences = 5
    merged = agent.store.upsert_incident(repeat)
    assert merged.occurrences == 6