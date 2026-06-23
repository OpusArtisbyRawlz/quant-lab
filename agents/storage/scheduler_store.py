"""
scheduler_store — reads and writes the Milestone 10 PR-6 ``scheduler_event``
table.

``scheduler_event`` is an append-only log of every scheduler decision about an
already human-approved idea (dispatched / succeeded / failed / retry_scheduled /
exhausted). The ResearchScheduler is the *sole writer*. Because the log is
append-only and carries the attempt number plus supporting evidence, every
scheduler decision — dispatch ordering, budget accounting, retries, recovery — is
fully reconstructible from storage.

This module is pure storage: it never approves, executes, or evaluates anything.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

# The fixed scheduler actions. Every appended event uses one of these.
ACTION_DISPATCHED = "dispatched"
ACTION_SUCCEEDED = "succeeded"
ACTION_FAILED = "failed"
ACTION_RETRY_SCHEDULED = "retry_scheduled"
ACTION_EXHAUSTED = "exhausted"

VALID_ACTIONS = frozenset({
    ACTION_DISPATCHED, ACTION_SUCCEEDED, ACTION_FAILED,
    ACTION_RETRY_SCHEDULED, ACTION_EXHAUSTED,
})

# Actions that mean a dispatched run is still outstanding (in-flight).
OPEN_ACTIONS = frozenset({ACTION_DISPATCHED, ACTION_RETRY_SCHEDULED})


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
# Writes (scheduler-only)
# ---------------------------------------------------------------------------

def append_event(
    idea_id: str,
    action: str,
    *,
    campaign_id: str | None = None,
    experiment_id: str | None = None,
    attempt: int = 1,
    reason: str | None = None,
    evidence: Any = None,
    db_path: Path = DB_PATH,
) -> int:
    """Append one immutable scheduler event. Returns the new row id."""
    if action not in VALID_ACTIONS:
        raise ValueError(f"unknown scheduler action: {action!r}")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO scheduler_event
                (idea_id, campaign_id, experiment_id, action, attempt,
                 reason, evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (idea_id, campaign_id, experiment_id, action, int(attempt),
             reason, _dumps(evidence), _utcnow()),
        )
        conn.commit()
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Reads (all derivations are pure functions of the stored log)
# ---------------------------------------------------------------------------

def list_events(
    *,
    idea_id: str | None = None,
    campaign_id: str | None = None,
    action: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Return events oldest-first (by autoincrement id), optionally filtered."""
    clauses, vals = [], []
    for col, val in (("idea_id", idea_id), ("campaign_id", campaign_id),
                     ("action", action)):
        if val is not None:
            clauses.append(f"{col} = ?")
            vals.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM scheduler_event {where} ORDER BY id", vals
        ).fetchall()
    return [_row(r) for r in rows]


def latest_event_per_idea(db_path: Path = DB_PATH) -> dict[str, dict[str, Any]]:
    """The most-recent event for every idea, keyed by idea_id."""
    out: dict[str, dict[str, Any]] = {}
    for e in list_events(db_path=db_path):     # oldest-first → last write wins
        out[e["idea_id"]] = e
    return out


def latest_event(idea_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM scheduler_event WHERE idea_id=? ORDER BY id DESC LIMIT 1",
            (idea_id,),
        ).fetchone()
    return _row(row) if row else None


def dispatch_count(idea_id: str, db_path: Path = DB_PATH) -> int:
    """How many times an idea has been dispatched (= attempts made)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM scheduler_event "
            "WHERE idea_id=? AND action=?",
            (idea_id, ACTION_DISPATCHED),
        ).fetchone()
    return int(row["n"]) if row else 0


def in_flight_idea_ids(db_path: Path = DB_PATH) -> set[str]:
    """Ideas whose most-recent event is an open (unresolved) dispatch."""
    return {
        idea_id for idea_id, e in latest_event_per_idea(db_path=db_path).items()
        if e["action"] in OPEN_ACTIONS
    }


def in_flight_count_by_campaign(db_path: Path = DB_PATH) -> dict[str, int]:
    """Open-dispatch counts grouped by campaign_id (None-keyed for ad-hoc)."""
    counts: dict[str, int] = {}
    for idea_id, e in latest_event_per_idea(db_path=db_path).items():
        if e["action"] in OPEN_ACTIONS:
            cid = e.get("campaign_id")
            counts[cid] = counts.get(cid, 0) + 1
    return counts


def distinct_idea_ids(db_path: Path = DB_PATH) -> list[str]:
    """Every idea_id that appears in the scheduler log (for reconciliation)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT idea_id FROM scheduler_event ORDER BY idea_id"
        ).fetchall()
    return [r["idea_id"] for r in rows]
