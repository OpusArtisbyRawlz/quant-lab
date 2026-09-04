"""
promotion_store — reads/writes the M11 PR-3 ``promotion_recommendation`` table.

``promotion_recommendation`` is a **rebuildable projection**: one row per
hypothesis, folded purely from PR-2's ``hypothesis_state`` posterior projection
plus provenance reads of the PR-1 ``evidence_event`` log. It is a droppable cache
— losing it never loses knowledge, because it re-derives deterministically from
the immutable evidence log.

This module is pure storage. It carries a *recommendation* only: writing a row
here never changes any hypothesis's authoritative stage and never mutates
historical evidence. The natural key is ``hypothesis_id`` and writes are
idempotent (``ON CONFLICT DO UPDATE``), so a re-fold reproduces identical rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

_JSON_COLUMNS = ("gate_detail",)


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


def upsert_recommendation(row: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert or replace one promotion recommendation (idempotent on hypothesis_id)."""
    row = dict(row)
    row.setdefault("method", "promotion_v1")
    if isinstance(row.get("gate_detail"), (list, dict)):
        row["gate_detail"] = json.dumps(row["gate_detail"], sort_keys=True)
    row["last_rebuilt_at"] = _utcnow()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    update = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "hypothesis_id")
    sql = (
        f"INSERT INTO promotion_recommendation ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(hypothesis_id) DO UPDATE SET {update}"
    )
    with get_connection(db_path) as conn:
        conn.execute(sql, list(row.values()))
        conn.commit()


def get_recommendation(hypothesis_id: str,
                       db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT * FROM promotion_recommendation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
    return _row(r) if r else None


def list_recommendations(*, recommended_stage: str | None = None,
                         db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        if recommended_stage is not None:
            rows = conn.execute(
                "SELECT * FROM promotion_recommendation WHERE recommended_stage = ? "
                "ORDER BY hypothesis_id",
                (recommended_stage,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM promotion_recommendation ORDER BY hypothesis_id"
            ).fetchall()
    return [_row(r) for r in rows]


def delete_recommendation(hypothesis_id: str, db_path: Path = DB_PATH) -> None:
    """Drop one hypothesis's recommendation (e.g. when its evidence is gone)."""
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM promotion_recommendation WHERE hypothesis_id = ?",
            (hypothesis_id,),
        )
        conn.commit()
