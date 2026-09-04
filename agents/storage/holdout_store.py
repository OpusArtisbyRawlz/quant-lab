"""
holdout_store — reads/writes the M11 PR-4 ``holdout_evaluation`` table.

``holdout_evaluation`` is a **rebuildable projection**: one row per hypothesis,
folded purely from the immutable ``evidence_event`` log (calendar-split into
IS/OOS, two stat_v1 posteriors, the four §5.2 gate conditions). It is a droppable
cache — losing it never loses knowledge, because it re-derives deterministically
from the log.

Pure storage: writing a row never mutates historical evidence. The natural key is
``hypothesis_id`` and writes are idempotent (``ON CONFLICT DO UPDATE``), so a
re-fold reproduces identical rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_holdout(row: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert or replace one holdout evaluation (idempotent on hypothesis_id)."""
    row = dict(row)
    row.setdefault("method", "holdout_v1")
    row["last_rebuilt_at"] = _utcnow()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    update = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "hypothesis_id")
    sql = (
        f"INSERT INTO holdout_evaluation ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(hypothesis_id) DO UPDATE SET {update}"
    )
    with get_connection(db_path) as conn:
        conn.execute(sql, list(row.values()))
        conn.commit()


def get_holdout(hypothesis_id: str,
                db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM holdout_evaluation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
    return dict(r) if r else None


def list_holdouts(*, passed: bool | None = None,
                  db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        if passed is not None:
            rows = conn.execute(
                "SELECT * FROM holdout_evaluation WHERE holdout_pass = ? "
                "ORDER BY hypothesis_id",
                (1 if passed else 0,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM holdout_evaluation ORDER BY hypothesis_id"
            ).fetchall()
    return [dict(r) for r in rows]


def delete_holdout(hypothesis_id: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM holdout_evaluation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        conn.commit()
