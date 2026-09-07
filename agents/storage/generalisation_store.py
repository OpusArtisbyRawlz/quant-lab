"""
generalisation_store — reads/writes the M11 PR-10 ``generalisation_matrix`` table.

``generalisation_matrix`` is a **rebuildable projection**: per (hypothesis ×
dimension) the §2.3 survival breakdown, re-derived deterministically from the
immutable evidence log. A droppable cache; losing it never loses knowledge.

Pure storage: writing never mutates historical evidence. All rows for a hypothesis
are replaced atomically on rebuild (DELETE + INSERT), keeping the projection an
exact function of the log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def replace_matrix(hypothesis_id: str, rows: list[dict[str, Any]],
                   db_path: Path = DB_PATH) -> None:
    """Atomically replace all dimension rows for one hypothesis (rebuildable)."""
    now = _utcnow()
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM generalisation_matrix WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        for row in rows:
            row = dict(row)
            row["hypothesis_id"] = hypothesis_id
            row.setdefault("method", "stat_v1")
            row["last_rebuilt_at"] = now
            cols = list(row.keys())
            placeholders = ", ".join("?" for _ in cols)
            conn.execute(
                f"INSERT INTO generalisation_matrix ({', '.join(cols)}) "
                f"VALUES ({placeholders})",
                list(row.values()),
            )
        conn.commit()


def list_matrix(hypothesis_id: str, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM generalisation_matrix WHERE hypothesis_id = ? "
            "ORDER BY dimension",
            (hypothesis_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_dimension(hypothesis_id: str, dimension: str,
                  db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM generalisation_matrix WHERE hypothesis_id = ? AND dimension = ?",
            (hypothesis_id, dimension),
        ).fetchone()
    return dict(r) if r else None


def delete_matrix(hypothesis_id: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM generalisation_matrix WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        conn.commit()


def distinct_hypotheses(db_path: Path = DB_PATH) -> list[str]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT hypothesis_id FROM generalisation_matrix ORDER BY hypothesis_id"
        ).fetchall()
    return [r["hypothesis_id"] for r in rows]
