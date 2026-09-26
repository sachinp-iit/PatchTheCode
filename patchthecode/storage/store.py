"""Local SQLite storage of incidents, investigations, and fix outcomes.

Powers deduplication (incidents by fingerprint), investigation history,
and the learning loop (tracking accepted/rejected fixes via PR outcomes).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from patchthecode.domain.models import FixProposal, Incident, InvestigationReport, PullRequestResult


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                occurrences INTEGER DEFAULT 1
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                status TEXT NOT NULL,
                report TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pull_requests (
                incident_id TEXT PRIMARY KEY,
                repository TEXT NOT NULL,
                url TEXT NOT NULL,
                number INTEGER NOT NULL,
                state TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get_incident(self, incident_id: str) -> Incident | None:
        row = self._conn.execute("SELECT payload FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if row is None:
            return None
        return Incident.model_validate_json(row[0])

    def has_fingerprint(self, fingerprint: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM incidents WHERE fingerprint = ? LIMIT 1", (fingerprint,)).fetchone()
        return row is not None

    def upsert_incident(self, incident: Incident) -> Incident:
        existing = self._conn.execute(
            "SELECT payload, occurrences FROM incidents WHERE id = ?", (incident.id,)
        ).fetchone()
        if existing is not None:
            stored = Incident.model_validate_json(existing[0])
            merged = incident.model_copy(
                update={
                    "occurrences": stored.occurrences + incident.occurrences,
                    "first_seen": min(stored.first_seen, incident.first_seen),
                    "last_seen": max(stored.last_seen, incident.last_seen),
                }
            )
            incident = merged
        self._conn.execute(
            "INSERT OR REPLACE INTO incidents VALUES (?, ?, ?, ?, ?, ?)",
            (
                incident.id,
                incident.fingerprint,
                incident.model_dump_json(),
                incident.first_seen.isoformat(),
                incident.last_seen.isoformat(),
                incident.occurrences,
            ),
        )
        self._conn.commit()
        return incident

    def save_report(self, report: InvestigationReport) -> None:
        self._conn.execute(
            "INSERT INTO reports (incident_id, status, report, created_at) VALUES (?, ?, ?, ?)",
            (
                report.incident.id,
                report.status,
                report.model_dump_json(),
                report.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    # --- learning loop: PR outcomes ---

    def save_pull_request(self, incident_id: str, repository: str, pr: PullRequestResult) -> None:
        """Persist a PR associated with an incident (upsert by incident)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO pull_requests (incident_id, repository, url, number, state, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                incident_id,
                repository,
                pr.url,
                pr.number,
                pr.state,
                datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def open_pull_requests(self) -> list[dict]:
        """Return PRs still awaiting review, keyed by incident."""
        rows = self._conn.execute(
            "SELECT incident_id, repository, url, number FROM pull_requests WHERE state = 'open'"
        ).fetchall()
        return [
            {
                "incident_id": row[0],
                "repository": row[1],
                "pr": PullRequestResult(url=row[2], number=row[3], state="open"),
            }
            for row in rows
        ]

    def mark_pull_request(self, incident_id: str, state: str) -> None:
        """Record the reviewed outcome of a PR (merged/closed)."""
        self._conn.execute(
            "UPDATE pull_requests SET state = ?, updated_at = ? WHERE incident_id = ?",
            (state, datetime.utcnow().isoformat(), incident_id),
        )
        self._conn.commit()

    def known_fix(self, fingerprint: str) -> tuple[FixProposal, PullRequestResult] | None:
        """Return the merged fix previously accepted for a fingerprint, if any.

        This is the learning fast-path: a recurring incident whose last fix
        landed as a merged PR is surfaced as `already_fixed` instead of being
        re-investigated from scratch.
        """
        row = self._conn.execute(
            """
            SELECT r.report, p.url, p.number
            FROM reports r
            JOIN incidents i ON i.id = r.incident_id
            JOIN pull_requests p ON p.incident_id = r.incident_id
            WHERE i.fingerprint = ? AND p.state = 'merged'
              AND json_extract(r.report, '$.fix') IS NOT NULL
            ORDER BY p.updated_at DESC
            LIMIT 1
            """,
            (fingerprint,),
        ).fetchone()
        if row is None:
            return None
        report = InvestigationReport.model_validate_json(row[0])
        pr = PullRequestResult(url=row[1], number=row[2], state="merged")
        assert report.fix is not None
        return report.fix, pr

    def close(self) -> None:
        self._conn.close()