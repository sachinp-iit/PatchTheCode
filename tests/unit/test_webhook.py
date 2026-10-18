"""Webhook ingestion: payload conversion and the HTTP endpoint."""

import asyncio
import json
from datetime import datetime

import pytest

from patchthecode.agent.sources import QueueFeed
from patchthecode.agent.watch import WatchLoop
from patchthecode.agent.webhook import IncidentWebhook
from patchthecode.detection.webhook import InvalidIncidentPayload, incident_from_payload
from patchthecode.domain import Severity
from patchthecode.domain.models import Incident, InvestigationReport

ENVELOPE = {
    "title": "NullPointerException in PaymentService.processPayment",
    "service": "payments-api",
    "severity": "critical",
    "occurrences": 7,
}


async def _request(
    port: int,
    body: bytes = b"",
    method: str = "POST",
    path: str = "/incidents",
    content_length: int | None = None,
) -> tuple[int, dict]:
    """Minimal raw HTTP/1.1 client; the server closes after each response."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    length = content_length if content_length is not None else len(body)
    head = (
        f"{method} {path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {length}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    writer.write(head.encode("latin-1") + body)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    await writer.wait_closed()
    header, _, payload = raw.partition(b"\r\n\r\n")
    status = int(header.split(b"\r\n")[0].split()[1])
    return status, json.loads(payload) if payload else {}


@pytest.fixture
async def webhook():
    queue = QueueFeed()
    server = IncidentWebhook(queue, port=0)
    port = await server.start()
    try:
        yield server, queue, port
    finally:
        await server.stop()


def test_incident_envelope_builds_fingerprinted_incident():
    incident = incident_from_payload(dict(ENVELOPE))
    assert incident.title == ENVELOPE["title"]
    assert incident.severity == Severity.CRITICAL
    assert incident.source.system == "webhook"
    assert incident.occurrences == 7
    assert incident.raw["service"] == "payments-api"
    # deterministic identity: the same alert twice is the same incident
    assert incident_from_payload(dict(ENVELOPE)).id == incident.id


def test_full_incident_payload_passes_through():
    ts = datetime.utcnow()
    payload = Incident(
        id="wh:1",
        fingerprint="fp-wh",
        source=incident_from_payload(dict(ENVELOPE)).source,
        severity=Severity.ERROR,
        title="boom",
        first_seen=ts,
        last_seen=ts,
        raw={},
    ).model_dump(mode="json")
    assert incident_from_payload(payload).id == "wh:1"


def test_invalid_payloads_rejected():
    for payload in (None, [], {}, {"description": "no title"}):
        try:
            incident_from_payload(payload)
        except InvalidIncidentPayload:
            continue
        raise AssertionError(f"expected InvalidIncidentPayload for {payload!r}")


async def test_webhook_accepts_alert_envelope(webhook):
    _, queue, port = webhook
    status, payload = await _request(port, json.dumps(ENVELOPE).encode())
    assert status == 202
    assert payload["queued"] == 1
    assert payload["incident_id"].startswith("webhook:alert:")
    queued = await queue.fetch()
    assert [i.title for i in queued] == [ENVELOPE["title"]]


async def test_webhook_accepts_full_incident_payload(webhook):
    _, queue, port = webhook
    incident = incident_from_payload(dict(ENVELOPE))
    status, _ = await _request(port, json.dumps(incident.model_dump(mode="json")).encode())
    assert status == 202
    queued = await queue.fetch()
    assert [i.id for i in queued] == [incident.id]


async def test_webhook_rejects_bad_requests(webhook):
    _, _, port = webhook
    status, payload = await _request(port, b"not json")
    assert (status, payload["error"]) == (400, "body is not valid JSON")

    status, payload = await _request(port, b"{}")
    assert status == 400
    assert "title" in payload["error"]

    status, _ = await _request(port, b"", method="GET")
    assert status == 405

    status, _ = await _request(port, b"{}", path="/nope")
    assert status == 404

    status, payload = await _request(port, b"", content_length=99_000_000)
    assert status == 413
    assert "exceeds" in payload["error"]


class _StubAgent:
    def __init__(self) -> None:
        self.handled: list[str] = []

    async def handle(self, incident: Incident) -> InvestigationReport:
        self.handled.append(incident.id)
        return InvestigationReport(incident=incident, status="no_evidence")

    async def poll_pull_requests(self) -> list[dict]:
        return []


async def test_webhook_fed_incidents_reach_the_watch_loop(webhook):
    _, queue, port = webhook
    status, _ = await _request(port, json.dumps(ENVELOPE).encode())
    assert status == 202

    agent = _StubAgent()
    loop = WatchLoop(agent=agent, feed=queue, max_cycles=1, poll_pull_requests=False)
    reports = await loop.run()

    assert [r.incident.title for r in reports] == [ENVELOPE["title"]]
    assert agent.handled == [reports[0].incident.id]
    # the pushed payload was consumed: nothing waits for the next cycle
    assert await queue.fetch() == []
