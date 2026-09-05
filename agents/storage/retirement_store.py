"""
retirement_store — reads/writes the M11 PR-6 ``retirement_evaluation`` table.

``retirement_evaluation`` is a **rebuildable projection**: one row per hypothesis,
folded purely from PR-2's ``hypothesis_state`` posterior. Because retirement is a
stateless function of the current posterior, the row is recomputed on every
rebuild — this is what makes reopen-on-new-evidence (§3.2) automatic and replay
safe. A droppable cache; losing it never loses knowledge.

Pure storage: writing a row never mutates historical evidence. Natural key
``hypothesis_id``; writes idempotent (``ON CONFLICT DO UPDATE``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

_JSON_COLUMNS = ("detail",)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r) -> dict[str, Any]:
    d = dict(r)
    for col in _JSON_COLUMNS:
        if col in d and d[col] is not None:
            try:
                d[col] = json.loads(d[col])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def upsert_retirement(row: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert or replace one retirement evaluation (idempotent on hypothesis_id)."""
    row = dict(row)
    row.setdefault("method", "retirement_v1")
    if isinstance(row.get("detail"), (dict, list)):
        row["detail"] = json.dumps(row["detail"], sort_keys=True)
    row["last_rebuilt_at"] = _utcnow()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    update = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "hypothesis_id")
    sql = (
        f"INSERT INTO retirement_evaluation ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(hypothesis_id) DO UPDATE SET {update}"
    )
    with get_connection(db_path) as conn:
        conn.execute(sql, list(row.values()))
        conn.commit()


def get_retirement(hypothesis_id: str,
                   db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM retirement_evaluation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
    return _row(r) if r else None


def list_retirements(*, retired: bool | None = None, state: str | None = None,
                     db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    clauses, vals = [], []
    if retired is not None:
        clauses.append("retired = ?")
        vals.append(1 if retired else 0)
    if state is not None:
        clauses.append("state = ?")
        vals.append(state)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM retirement_evaluation {where} ORDER BY hypothesis_id", vals
        ).fetchall()
    return [_row(r) for r in rows]


def delete_retirement(hypothesis_id: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM retirement_evaluation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        conn.commit()
