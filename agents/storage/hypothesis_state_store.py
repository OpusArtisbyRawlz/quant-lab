"""
hypothesis_state_store — reads/writes the M11 PR-2 posterior projections.

Two **rebuildable projection** tables, folded purely from the immutable
``evidence_event`` log by ``EvidenceProjector``:

  * ``hypothesis_state`` — one row per hypothesis: the posterior over the latent
    effect (mean, sd, credible interval) and the four separated axes Q/R/G/V.
  * ``context_cell_posterior`` — one row per (hypothesis × context cell): the
    cell-level posterior.

Both are droppable caches — losing them never loses knowledge, because they
re-derive from the log. This module is pure storage. It carries no decision:
``stage`` is written as the initial ``'Candidate'`` value; promotion/retirement
transitions are a later PR.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# hypothesis_state (hypothesis-grain projection)
# ---------------------------------------------------------------------------

def upsert_hypothesis_state(row: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert or replace one hypothesis_state projection row (idempotent)."""
    row = dict(row)
    row.setdefault("stage", "Candidate")
    row.setdefault("method", "stat_v1")
    row["last_rebuilt_at"] = _utcnow()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    update = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "hypothesis_id")
    sql = (
        f"INSERT INTO hypothesis_state ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(hypothesis_id) DO UPDATE SET {update}"
    )
    with get_connection(db_path) as conn:
        conn.execute(sql, list(row.values()))
        conn.commit()


def get_hypothesis_state(hypothesis_id: str,
                         db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM hypothesis_state WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
    return dict(r) if r else None


def list_hypothesis_states(*, stage: str | None = None,
                           db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        if stage is not None:
            rows = conn.execute(
                "SELECT * FROM hypothesis_state WHERE stage = ? ORDER BY hypothesis_id",
                (stage,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM hypothesis_state ORDER BY hypothesis_id"
            ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# context_cell_posterior (cell-grain projection)
# ---------------------------------------------------------------------------

def replace_cell_posteriors(hypothesis_id: str, rows: list[dict[str, Any]],
                            db_path: Path = DB_PATH) -> None:
    """Atomically replace all cell posteriors for one hypothesis (rebuildable)."""
    now = _utcnow()
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM context_cell_posterior WHERE hypothesis_id = ?",
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
                f"INSERT INTO context_cell_posterior ({', '.join(cols)}) "
                f"VALUES ({placeholders})",
                list(row.values()),
            )
        conn.commit()


def list_cell_posteriors(hypothesis_id: str,
                         db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM context_cell_posterior WHERE hypothesis_id = ? "
            "ORDER BY market, universe, regime, bar_type",
            (hypothesis_id,),
        ).fetchall()
    return [dict(r) for r in rows]
