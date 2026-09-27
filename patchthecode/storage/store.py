"""Local SQLite storage of incidents, investigations, and fix outcomes.

Powers deduplication (incidents by fingerprint), investigation history,
and the learning loop (tracking accepted/rejected fixes via PR outcomes).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

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
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                incident_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                diff TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
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
        """Record the reviewed outcome of a PR (merged/closed).

        A PR closed without merging counts as a rejected fix and is recorded
        so the next attempt for the same fingerprint can avoid it.
        """
        self._conn.execute(
            "UPDATE pull_requests SET state = ?, updated_at = ? WHERE incident_id = ?",
            (state, datetime.utcnow().isoformat(), incident_id),
        )
        if state == "closed":
            self._record_rejection(incident_id)
        self._conn.commit()

    def _record_rejection(self, incident_id: str) -> None:
        """Persist the latest fix for an incident as a rejection of its fingerprint."""
        existing = self._conn.execute(
            "SELECT 1 FROM rejections WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if existing is not None:
            return
        row = self._conn.execute(
            """
            SELECT r.report, i.fingerprint
            FROM reports r
            JOIN incidents i ON i.id = r.incident_id
            WHERE r.incident_id = ? AND json_extract(r.report, '$.fix') IS NOT NULL
            ORDER BY r.created_at DESC
            LIMIT 1
            """,
            (incident_id,),
        ).fetchone()
        if row is None:
            return
        report = InvestigationReport.model_validate_json(row[0])
        fingerprint = row[1]
        assert report.fix is not None
        if not report.fix.diff:
            return
        self._conn.execute(
            "INSERT INTO rejections (fingerprint, incident_id, summary, diff, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                fingerprint,
                incident_id,
                report.fix.summary,
                report.fix.diff,
                "closed without merge",
                datetime.utcnow().isoformat(),
            ),
        )

    def has_rejections(self, fingerprint: str) -> bool:
        """True when a reviewer already rejected a fix for this fingerprint."""
        row = self._conn.execute(
            "SELECT 1 FROM rejections WHERE fingerprint = ? LIMIT 1", (fingerprint,)
        ).fetchone()
        return row is not None

    def rejected_fixes(self, fingerprint: str) -> list[dict]:
        """The rejected fix attempts for a fingerprint, newest first."""
        rows = self._conn.execute(
            "SELECT summary, diff, reason, created_at FROM rejections WHERE fingerprint = ?"
            " ORDER BY created_at DESC",
            (fingerprint,),
        ).fetchall()
        return [
            {"summary": row[0], "diff": row[1], "reason": row[2], "created_at": row[3]}
            for row in rows
        ]

    def all_rejections(self) -> list[dict]:
        """Every recorded rejection across fingerprints, newest first."""
        rows = self._conn.execute(
            "SELECT fingerprint, incident_id, summary, diff, reason, created_at FROM rejections"
            " ORDER BY created_at DESC"
        ).fetchall()
        return [
            {
                "fingerprint": row[0],
                "incident_id": row[1],
                "summary": row[2],
                "diff": row[3],
                "reason": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    def summary(self) -> dict[str, int]:
        """Operating totals: what the store knows at a glance."""
        return {
            "incidents": self._conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0],
            "investigations": self._conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
            "open_prs": self._conn.execute(
                "SELECT COUNT(*) FROM pull_requests WHERE state = 'open'"
            ).fetchone()[0],
            "merged_fixes": self._conn.execute(
                "SELECT COUNT(*) FROM pull_requests WHERE state = 'merged'"
            ).fetchone()[0],
            "rejections": self._conn.execute("SELECT COUNT(*) FROM rejections").fetchone()[0],
        }

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

    def successful_strategies(
        self, fingerprint: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Rank evidence strategies that led to merged fixes.

        Looks at investigation reports whose incident ended in a merged PR and
        aggregates how often each (source_system, kind) evidence combination
        showed up, so the planner can lean on evidence that has previously
        produced fixes reviewers accepted.
        """
        sql = """
            SELECT r.report
            FROM reports r
            JOIN pull_requests p ON p.incident_id = r.incident_id
            JOIN incidents i ON i.id = r.incident_id
            WHERE p.state = 'merged'
        """
        params: list[str] = []
        if fingerprint:
            sql += " AND i.fingerprint = ?"
            params.append(fingerprint)
        counts: dict[tuple[str, str], int] = {}
        for (report_json,) in self._conn.execute(sql, params).fetchall():
            try:
                evidence = json.loads(report_json).get("evidence") or []
            except (TypeError, ValueError):
                continue
            for item in evidence:
                system = str(item.get("source_system") or "unknown")
                kind = str(item.get("kind") or "unknown")
                counts[(system, kind)] = counts.get((system, kind), 0) + 1
        ranked = [
            {"system": system, "kind": kind, "count": count}
            for (system, kind), count in sorted(
                counts.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])
            )
        ]
        return ranked[:limit]

    def playbook(self, fingerprint: str) -> dict | None:
        """Learning summary for a fingerprint, compiled from its history.

        Consolidates recurrences, any previously merged fix, and every rejected
        attempt so re-investigations of a recurring fingerprint can start from
        what was already tried rather than from scratch.
        """
        agg = self._conn.execute(
            "SELECT COUNT(*), MIN(first_seen), MAX(last_seen) FROM incidents WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if agg is None or agg[0] == 0:
            return None
        latest = self._conn.execute(
            "SELECT json_extract(payload, '$.title') FROM incidents"
            " WHERE fingerprint = ? ORDER BY last_seen DESC LIMIT 1",
            (fingerprint,),
        ).fetchone()
        merged = self.known_fix(fingerprint)
        merged_entry = None
        if merged is not None:
            fix, pr = merged
            merged_entry = {"summary": fix.summary, "diff": fix.diff, "pr": pr.url}
        return {
            "fingerprint": fingerprint,
            "recurrences": agg[0],
            "first_seen": agg[1],
            "last_seen": agg[2],
            "last_title": latest[0] if latest else None,
            "merged": merged_entry,
            "rejections": self.rejected_fixes(fingerprint),
        }

    def playbooks(self) -> list[dict]:
        """Every fingerprint's debugging playbook, most recent first."""
        rows = self._conn.execute(
            "SELECT fingerprint FROM incidents GROUP BY fingerprint ORDER BY MAX(last_seen) DESC"
        ).fetchall()
        books = []
        for (fingerprint,) in rows:
            book = self.playbook(fingerprint)
            if book is not None:
                books.append(book)
        return books

    def close(self) -> None:
        self._conn.close()