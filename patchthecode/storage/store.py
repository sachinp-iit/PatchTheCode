"""Local SQLite storage of incidents, investigations, and fix outcomes.

Powers deduplication (incidents by fingerprint), investigation history,
and the Phase-3 learning loop (accepted/rejected fixes).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from patchthecode.domain.models import Incident, InvestigationReport


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

    def close(self) -> None:
        self._conn.close()