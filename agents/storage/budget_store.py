"""
budget_store — reads/writes the M11 PR-7 ``budget_allocation`` table.

``budget_allocation`` is a **rebuildable projection**: one row per hypothesis,
folded from the posterior + retirement determination by the BudgetEngine. A
droppable cache; losing it never loses knowledge, because it re-derives
deterministically from those projections.

Pure storage: writing a row never mutates historical evidence. Natural key
``hypothesis_id``; writes idempotent (``ON CONFLICT DO UPDATE``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_budget(row: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert or replace one budget allocation (idempotent on hypothesis_id)."""
    row = dict(row)
    row.setdefault("method", "budget_v1")
    row["last_rebuilt_at"] = _utcnow()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    update = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "hypothesis_id")
    sql = (
        f"INSERT INTO budget_allocation ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(hypothesis_id) DO UPDATE SET {update}"
    )
    with get_connection(db_path) as conn:
        conn.execute(sql, list(row.values()))
        conn.commit()


def get_budget(hypothesis_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM budget_allocation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
    return dict(r) if r else None


def list_budgets(*, retired: bool | None = None,
                 db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        if retired is not None:
            rows = conn.execute(
                "SELECT * FROM budget_allocation WHERE retired = ? ORDER BY hypothesis_id",
                (1 if retired else 0,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM budget_allocation ORDER BY hypothesis_id"
            ).fetchall()
    return [dict(r) for r in rows]


def budget_map(db_path: Path = DB_PATH) -> dict[str, int]:
    """``{hypothesis_id: b_experiments}`` — the admission caps for the quota seam."""
    return {r["hypothesis_id"]: r["b_experiments"]
            for r in list_budgets(db_path=db_path)}


def delete_budget(hypothesis_id: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM budget_allocation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        conn.commit()
