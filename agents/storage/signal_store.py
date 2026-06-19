"""
Signal library — reads and writes the signal_library table.

Stores feature/signal records including partial signals, rejected experiments,
and useful observations so the Idea Generator can combine weak signals into
stronger strategies later.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def upsert_signal(record: dict[str, Any], db_path: Path = DB_PATH) -> int:
    """
    Insert or update a signal record by feature_name (unique key).
    Returns the row id.
    """
    record = _coerce(record)
    now = datetime.now(timezone.utc).isoformat()
    record.setdefault("created_at", now)
    record["updated_at"] = now

    columns = list(record.keys())
    placeholders = ", ".join("?" for _ in columns)
    col_str = ", ".join(columns)
    update_str = ", ".join(
        f"{c} = excluded.{c}" for c in columns if c != "feature_name"
    )

    sql = f"""
        INSERT INTO signal_library ({col_str}) VALUES ({placeholders})
        ON CONFLICT(feature_name) DO UPDATE SET {update_str}, updated_at = excluded.updated_at
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(sql, list(record.values()))
        conn.commit()
        # RETURNING not available in older SQLite; fetch the rowid separately
        row = conn.execute(
            "SELECT id FROM signal_library WHERE feature_name = ?",
            (record["feature_name"],),
        ).fetchone()
        return row["id"]


def add_experiment_to_signal(feature_name: str, experiment_id: str,
                              db_path: Path = DB_PATH) -> None:
    """Append an experiment_id to the signal's experiment_ids list."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT experiment_ids FROM signal_library WHERE feature_name = ?",
            (feature_name,),
        ).fetchone()
        if not row:
            return
        ids: list[str] = json.loads(row["experiment_ids"] or "[]")
        if experiment_id not in ids:
            ids.append(experiment_id)
            conn.execute(
                "UPDATE signal_library SET experiment_ids = ?, updated_at = ? "
                "WHERE feature_name = ?",
                (json.dumps(ids), datetime.now(timezone.utc).isoformat(), feature_name),
            )
            conn.commit()


def update_signal_status(feature_name: str, status: str,
                         notes: str | None = None, db_path: Path = DB_PATH) -> None:
    sets = ["keep_reject_retest = ?", "updated_at = ?"]
    vals: list[Any] = [status, datetime.now(timezone.utc).isoformat()]
    if notes is not None:
        sets.append("notes = ?")
        vals.append(notes)
    vals.append(feature_name)
    with get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE signal_library SET {', '.join(sets)} WHERE feature_name = ?", vals
        )
        conn.commit()


def update_lifecycle(
    feature_name: str,
    lifecycle_state: str,
    *,
    generalization_class: str | None = None,
    promoted_at: str | None = None,
    retired_at: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Milestone 9: set the lifecycle_state / generalization_class of a signal.

    Only the fields supplied are written. `last_evaluated_at` is always stamped
    so the signal-library lifecycle (TD-4) records when a decision was last made.
    """
    now = datetime.now(timezone.utc).isoformat()
    sets = ["lifecycle_state = ?", "last_evaluated_at = ?", "updated_at = ?"]
    vals: list[Any] = [lifecycle_state, now, now]
    if generalization_class is not None:
        sets.append("generalization_class = ?")
        vals.append(generalization_class)
    if promoted_at is not None:
        sets.append("promoted_at = ?")
        vals.append(promoted_at)
    if retired_at is not None:
        sets.append("retired_at = ?")
        vals.append(retired_at)
    vals.append(feature_name)
    with get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE signal_library SET {', '.join(sets)} WHERE feature_name = ?",
            vals,
        )
        conn.commit()


def log_lifecycle_event(
    feature_name: str,
    to_state: str,
    *,
    from_state: str | None = None,
    reason_code: str | None = None,
    context_scope: str | None = None,
    evidence_n: int | None = None,
    db_path: Path = DB_PATH,
) -> int:
    """Append an immutable lifecycle-transition audit row (M9). Returns row id."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO signal_lifecycle_events
                (feature_name, from_state, to_state, reason_code,
                 context_scope, evidence_n, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (feature_name, from_state, to_state, reason_code, context_scope,
             evidence_n, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid


def list_lifecycle_events(feature_name: str | None = None,
                          db_path: Path = DB_PATH) -> list[dict]:
    clause, vals = "", []
    if feature_name is not None:
        clause = "WHERE feature_name = ?"
        vals.append(feature_name)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_lifecycle_events {clause} ORDER BY id", vals
        ).fetchall()
        return [dict(r) for r in rows]


def list_by_lifecycle(lifecycle_state: str | None = None,
                      db_path: Path = DB_PATH) -> list[dict]:
    """List signals filtered by lifecycle_state (M9). None returns all."""
    clause, vals = "", []
    if lifecycle_state is not None:
        clause = "WHERE lifecycle_state = ?"
        vals.append(lifecycle_state)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_library {clause} ORDER BY feature_name", vals
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_signal(feature_name: str, db_path: Path = DB_PATH) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM signal_library WHERE feature_name = ?", (feature_name,)
        ).fetchone()
        return _deserialize(dict(row)) if row else None


def list_signals(signal_type: str | None = None, status: str | None = None,
                 db_path: Path = DB_PATH) -> list[dict]:
    clauses, vals = [], []
    if signal_type:
        clauses.append("signal_type = ?")
        vals.append(signal_type)
    if status:
        clauses.append("keep_reject_retest = ?")
        vals.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_library {where} ORDER BY feature_name", vals
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


def get_combinable_signals(db_path: Path = DB_PATH) -> list[dict]:
    """Return keep/retest signals that have at least one possible combination."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM signal_library "
            "WHERE keep_reject_retest IN ('keep', 'retest') "
            "AND possible_combinations IS NOT NULL "
            "AND possible_combinations != '[]' "
            "ORDER BY performance_contribution DESC NULLS LAST"
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


def get_weak_signals(db_path: Path = DB_PATH) -> list[dict]:
    """Rejected or retest signals — candidates for blending experiments."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM signal_library WHERE keep_reject_retest IN ('reject', 'retest') "
            "ORDER BY updated_at DESC"
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


def signal_summary(db_path: Path = DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM signal_library").fetchone()[0]
        by_status = conn.execute(
            "SELECT keep_reject_retest, COUNT(*) AS n FROM signal_library GROUP BY keep_reject_retest"
        ).fetchall()
        by_type = conn.execute(
            "SELECT signal_type, COUNT(*) AS n FROM signal_library GROUP BY signal_type"
        ).fetchall()
        return {
            "total": total,
            "by_status": {r["keep_reject_retest"]: r["n"] for r in by_status},
            "by_type": {r["signal_type"]: r["n"] for r in by_type},
        }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _coerce(record: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in record.items():
        if isinstance(v, (list, dict)):
            out[k] = json.dumps(v)
        else:
            out[k] = v
    return out


def _deserialize(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("experiment_ids", "possible_combinations"):
        if key in record and isinstance(record[key], str):
            try:
                record[key] = json.loads(record[key])
            except (json.JSONDecodeError, TypeError):
                record[key] = []
    return record
