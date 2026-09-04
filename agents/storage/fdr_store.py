"""
fdr_store — reads/writes the M11 PR-5 ``fdr_evaluation`` table.

``fdr_evaluation`` is a **rebuildable projection**: one row per hypothesis, folded
over the whole active population from the stat_v1 lfdr (Bayesian FDR set) and the
one-sided frequentist p-values (BH q-values). It is a droppable cache — losing it
never loses knowledge, because it re-derives deterministically from the posterior
projection + the immutable evidence log.

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


def upsert_fdr(row: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert or replace one FDR evaluation (idempotent on hypothesis_id)."""
    row = dict(row)
    row.setdefault("method", "fdr_v1")
    row["last_rebuilt_at"] = _utcnow()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    update = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "hypothesis_id")
    sql = (
        f"INSERT INTO fdr_evaluation ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(hypothesis_id) DO UPDATE SET {update}"
    )
    with get_connection(db_path) as conn:
        conn.execute(sql, list(row.values()))
        conn.commit()


def get_fdr(hypothesis_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM fdr_evaluation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
    return dict(r) if r else None


def list_fdr(*, bayes_admitted: bool | None = None,
             db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        if bayes_admitted is not None:
            rows = conn.execute(
                "SELECT * FROM fdr_evaluation WHERE bayes_admitted = ? "
                "ORDER BY hypothesis_id",
                (1 if bayes_admitted else 0,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fdr_evaluation ORDER BY hypothesis_id"
            ).fetchall()
    return [dict(r) for r in rows]


def delete_fdr(hypothesis_id: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM fdr_evaluation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        conn.commit()
