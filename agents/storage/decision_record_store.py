"""
decision_record_store — reads/writes the M11 PR-11 ``decision_record`` table.

``decision_record`` is a **rebuildable projection**: one row per
(decision_type, subject) explaining a promote / retire / reject decision, folded
purely from the existing M11 projections + evidence provenance. A droppable cache;
losing it never loses knowledge.

Pure storage: writing never mutates historical evidence. Natural key
``(decision_type, subject_id)``; writes idempotent (``ON CONFLICT DO UPDATE``).
JSON columns are decoded on read.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

_JSON_COLUMNS = ("chosen", "evidence_used",
                 "supporting_experiment_ids", "contradictory_experiment_ids")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r) -> dict[str, Any]:
    d = dict(r)
    for col in _JSON_COLUMNS:
        if d.get(col) is not None:
            try:
                d[col] = json.loads(d[col])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def upsert_record(row: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert or replace one decision record (idempotent on type+subject)."""
    row = dict(row)
    for col in _JSON_COLUMNS:
        if isinstance(row.get(col), (list, dict)):
            row[col] = json.dumps(row[col], sort_keys=True)
    row["created_at"] = _utcnow()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    keys = {"decision_type", "subject_id"}
    update = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
    sql = (
        f"INSERT INTO decision_record ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(decision_type, subject_id) DO UPDATE SET {update}"
    )
    with get_connection(db_path) as conn:
        conn.execute(sql, list(row.values()))
        conn.commit()


def get_record(decision_type: str, subject_id: str,
               db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM decision_record WHERE decision_type = ? AND subject_id = ?",
            (decision_type, subject_id),
        ).fetchone()
    return _row(r) if r else None


def list_records(*, decision_type: str | None = None, subject_id: str | None = None,
                 db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    clauses, vals = [], []
    if decision_type is not None:
        clauses.append("decision_type = ?"); vals.append(decision_type)
    if subject_id is not None:
        clauses.append("subject_id = ?"); vals.append(subject_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM decision_record {where} ORDER BY decision_type, subject_id", vals
        ).fetchall()
    return [_row(r) for r in rows]


def delete_record(decision_type: str, subject_id: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM decision_record WHERE decision_type = ? AND subject_id = ?",
            (decision_type, subject_id),
        )
        conn.commit()
