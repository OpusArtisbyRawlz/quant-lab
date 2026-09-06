"""
failure_store — reads/writes the M11 PR-9 ``failure_reason`` table.

``failure_reason`` is a **rebuildable projection**: one row per failed/rejected
experiment, classified deterministically from the immutable ``evidence_event`` log
by the FailureClassifier. A droppable cache — losing it never loses knowledge,
because it re-derives from the log.

Pure storage: writing a row never mutates historical evidence, and it never
touches the prose ``lessons_learned`` (of which this is a structured sibling).
Natural key ``experiment_id``; writes idempotent (``ON CONFLICT DO UPDATE``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r) -> dict[str, Any]:
    d = dict(r)
    if d.get("evidence") is not None:
        try:
            d["evidence"] = json.loads(d["evidence"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def upsert_failure(experiment_id: str, reason_code: str, evidence: Any = None,
                   method: str = "failure_v1", db_path: Path = DB_PATH) -> None:
    """Insert or replace one failure classification (idempotent on experiment_id)."""
    ev = None if evidence is None else json.dumps(evidence, sort_keys=True)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO failure_reason (experiment_id, reason_code, evidence, method, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(experiment_id) DO UPDATE SET
                reason_code=excluded.reason_code,
                evidence=excluded.evidence,
                method=excluded.method,
                created_at=excluded.created_at
            """,
            (experiment_id, reason_code, ev, method, _utcnow()),
        )
        conn.commit()


def get_failure(experiment_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM failure_reason WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
    return _row(r) if r else None


def list_failures(*, reason_code: str | None = None,
                  db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        if reason_code is not None:
            rows = conn.execute(
                "SELECT * FROM failure_reason WHERE reason_code = ? ORDER BY experiment_id",
                (reason_code,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM failure_reason ORDER BY experiment_id"
            ).fetchall()
    return [_row(r) for r in rows]


def delete_failure(experiment_id: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM failure_reason WHERE experiment_id = ?", (experiment_id,)
        )
        conn.commit()
