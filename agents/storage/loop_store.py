"""
loop_store — reads and writes the Milestone 10 PR-7 ``loop_checkpoint`` table.

``loop_checkpoint`` is an append-only log of every research-loop tick phase
boundary (``started`` / ``completed``) for each of the six loop phases —
recover, generate, schedule, dispatch, learn, checkpoint. The ResearchLoop is
the *sole writer*. Because the log is append-only and each tick carries a
deterministic ``tick_id``, the loop's progress is fully reconstructible from
storage: on restart the loop can see exactly which phases of which tick already
completed and resume without repeating side effects.

This module is pure storage: it never generates, schedules, dispatches, or
executes anything.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

# Phase names — the fixed six-phase tick.
PHASE_RECOVER = "recover"
PHASE_GENERATE = "generate"
PHASE_SCHEDULE = "schedule"
PHASE_DISPATCH = "dispatch"
PHASE_LEARN = "learn"
PHASE_CHECKPOINT = "checkpoint"

PHASES = (
    PHASE_RECOVER, PHASE_GENERATE, PHASE_SCHEDULE,
    PHASE_DISPATCH, PHASE_LEARN, PHASE_CHECKPOINT,
)

STATUS_STARTED = "started"
STATUS_COMPLETED = "completed"
VALID_STATUS = frozenset({STATUS_STARTED, STATUS_COMPLETED})


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True)


def _loads(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _row(r) -> dict[str, Any]:
    d = dict(r)
    d["evidence"] = _loads(d.get("evidence"))
    return d


# ---------------------------------------------------------------------------
# Writes (loop-only)
# ---------------------------------------------------------------------------

def append_checkpoint(
    tick_id: str,
    phase: str,
    status: str,
    *,
    campaign_id: str | None = None,
    evidence: Any = None,
    db_path: Path = DB_PATH,
) -> int:
    """Append one immutable checkpoint row. Returns the new row id."""
    if phase not in PHASES:
        raise ValueError(f"unknown loop phase: {phase!r}")
    if status not in VALID_STATUS:
        raise ValueError(f"unknown checkpoint status: {status!r}")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO loop_checkpoint
                (tick_id, campaign_id, phase, status, evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tick_id, campaign_id, phase, status, _dumps(evidence), _utcnow()),
        )
        conn.commit()
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Reads (pure functions of the stored log)
# ---------------------------------------------------------------------------

def list_checkpoints(
    *,
    tick_id: str | None = None,
    phase: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Return checkpoints oldest-first (by id), optionally filtered."""
    clauses, vals = [], []
    for col, val in (("tick_id", tick_id), ("phase", phase)):
        if val is not None:
            clauses.append(f"{col} = ?")
            vals.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM loop_checkpoint {where} ORDER BY id", vals
        ).fetchall()
    return [_row(r) for r in rows]


def phase_completed(
    tick_id: str, phase: str, db_path: Path = DB_PATH
) -> bool:
    """True if the given phase of the given tick has a ``completed`` row.

    This is the resumability primitive: a phase with a completed checkpoint has
    already run its side effects and must not be repeated within the same tick.
    """
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM loop_checkpoint "
            "WHERE tick_id=? AND phase=? AND status=? LIMIT 1",
            (tick_id, phase, STATUS_COMPLETED),
        ).fetchone()
    return row is not None


def tick_completed(tick_id: str, db_path: Path = DB_PATH) -> bool:
    """True once the terminal ``checkpoint`` phase has completed for the tick."""
    return phase_completed(tick_id, PHASE_CHECKPOINT, db_path=db_path)


def completed_phases(tick_id: str, db_path: Path = DB_PATH) -> set[str]:
    """The set of phases that have completed for a tick (for recovery/inspection)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT phase FROM loop_checkpoint "
            "WHERE tick_id=? AND status=?",
            (tick_id, STATUS_COMPLETED),
        ).fetchall()
    return {r["phase"] for r in rows}


def distinct_tick_ids(db_path: Path = DB_PATH) -> list[str]:
    """Every tick_id that appears in the checkpoint log, oldest-first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT tick_id, MIN(id) AS first_id FROM loop_checkpoint "
            "GROUP BY tick_id ORDER BY first_id"
        ).fetchall()
    return [r["tick_id"] for r in rows]


def latest_tick_id(db_path: Path = DB_PATH) -> str | None:
    """The most-recently-started tick_id, or None if the loop has never run."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT tick_id FROM loop_checkpoint ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["tick_id"] if row else None
