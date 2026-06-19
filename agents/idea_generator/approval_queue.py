"""
approval_queue.py — SQLite-backed persistence for the human approval queue.

Backs the `pending_ideas` table. Survives restarts; every decision is
persisted and auditable. The approval surface is intentionally minimal (M6):

    enqueue(...)            -- record a validated idea as `pending`
    record_rejected(...)    -- record a validation/parse rejection as `rejected`
    list_pending(...)       -- read-only view of pending ideas
    approve_idea(idea_id)   -- mark approved
    reject_idea(idea_id)    -- mark rejected (human decision)

M6 stops at an `approved` row. Nothing here executes, schedules, or promotes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agents.protocol import ProposedIdea
from agents.storage.db import get_connection, DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    base = "".join(c.lower() if c.isalnum() else "_" for c in text).strip("_")
    parts = [p for p in base.split("_") if p][:4]
    return "_".join(parts) or "idea"


def next_idea_id(db_path: Path = DB_PATH) -> str:
    """Return the next zero-padded idea id, e.g. 'idea_007'. Slug appended by caller."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT idea_id FROM pending_ideas ORDER BY created_at DESC, idea_id DESC LIMIT 1"
        ).fetchone()
    n = 0
    if row and row["idea_id"].startswith("idea_"):
        try:
            n = int(row["idea_id"].split("_")[1])
        except (IndexError, ValueError):
            n = 0
    return f"idea_{n + 1:03d}"


def make_idea_id(idea: ProposedIdea, db_path: Path = DB_PATH) -> str:
    return f"{next_idea_id(db_path)}_{_slug(idea.hypothesis)}"


def enqueue(
    idea: ProposedIdea,
    idea_id: str,
    *,
    cycle_id: str | None = None,
    db_path: Path = DB_PATH,
) -> str:
    """Persist a validation-passing idea as `pending`. Returns the idea_id."""
    metadata = {"scores": idea.scores or {}}
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pending_ideas
                (idea_id, cycle_id, hypothesis, suggested_signals, rationale,
                 source_model, market, universe, metadata, status, validation_ok,
                 validation_reasons, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?)
            """,
            (
                idea_id,
                cycle_id,
                idea.hypothesis,
                json.dumps(list(idea.suggested_signals)),
                idea.rationale,
                idea.source_model,
                idea.market or "unknown",
                idea.universe or "unknown",
                json.dumps(metadata),
                json.dumps([]),
                _now(),
            ),
        )
        conn.commit()
    return idea_id


def record_rejected(
    idea: ProposedIdea,
    idea_id: str,
    reasons: list[str],
    *,
    cycle_id: str | None = None,
    db_path: Path = DB_PATH,
) -> str:
    """Persist an idea that FAILED validation as `rejected` with reasons."""
    metadata = {"scores": idea.scores or {}}
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pending_ideas
                (idea_id, cycle_id, hypothesis, suggested_signals, rationale,
                 source_model, market, universe, metadata, status, validation_ok,
                 validation_reasons, created_at, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'rejected', 0, ?, ?, ?)
            """,
            (
                idea_id,
                cycle_id,
                idea.hypothesis,
                json.dumps(list(idea.suggested_signals)),
                idea.rationale,
                idea.source_model,
                idea.market or "unknown",
                idea.universe or "unknown",
                json.dumps(metadata),
                json.dumps(reasons),
                _now(),
                _now(),
            ),
        )
        conn.commit()
    return idea_id


def list_pending(db_path: Path = DB_PATH) -> list[dict]:
    """Read-only view of all pending ideas, oldest first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pending_ideas WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


def list_approved(db_path: Path = DB_PATH) -> list[dict]:
    """Read-only view of ideas approved-for-execution, oldest first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pending_ideas WHERE status = 'approved' ORDER BY created_at"
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


def get_approved(idea_id: str, db_path: Path = DB_PATH) -> dict | None:
    """Return a single approved idea, or None if not approved / not found."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM pending_ideas WHERE idea_id = ? AND status = 'approved'",
            (idea_id,),
        ).fetchone()
        return _deserialize(dict(row)) if row else None


def mark_executed(idea_id: str, experiment_id: str, db_path: Path = DB_PATH) -> bool:
    """
    Transition an approved idea to `executed` and link its experiment_id.

    Returns True if an approved row was updated. Idempotent: only `approved`
    rows transition, so re-running execution never double-processes an idea.
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE pending_ideas
               SET status = 'executed', experiment_id = ?
             WHERE idea_id = ? AND status = 'approved'
            """,
            (experiment_id, idea_id),
        )
        conn.commit()
        return cur.rowcount > 0


def reject_approved(idea_id: str, note: str = "", db_path: Path = DB_PATH) -> bool:
    """
    Transition an `approved` idea to `rejected` (execution-time validation
    failure). Returns True if an approved row was updated. Only `approved` rows
    transition, so this is idempotent alongside mark_executed.
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE pending_ideas
               SET status = 'rejected', reviewed_at = ?, reviewer_note = ?
             WHERE idea_id = ? AND status = 'approved'
            """,
            (_now(), note, idea_id),
        )
        conn.commit()
        return cur.rowcount > 0


def get_idea(idea_id: str, db_path: Path = DB_PATH) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM pending_ideas WHERE idea_id = ?", (idea_id,)
        ).fetchone()
        return _deserialize(dict(row)) if row else None


def list_by_status(status: str, db_path: Path = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pending_ideas WHERE status = ? ORDER BY created_at",
            (status,),
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


def approve_idea(idea_id: str, note: str = "", db_path: Path = DB_PATH) -> bool:
    """
    Mark a pending idea approved. Returns True if a pending row was updated.
    Idempotent: approving an already-approved idea is a no-op returning False.
    """
    return _decide(idea_id, "approved", note, db_path)


def reject_idea(idea_id: str, note: str = "", db_path: Path = DB_PATH) -> bool:
    """Mark a pending idea rejected (human decision)."""
    return _decide(idea_id, "rejected", note, db_path)


def _decide(idea_id: str, status: str, note: str, db_path: Path) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE pending_ideas
               SET status = ?, reviewed_at = ?, reviewer_note = ?
             WHERE idea_id = ? AND status = 'pending'
            """,
            (status, _now(), note, idea_id),
        )
        conn.commit()
        return cur.rowcount > 0


def _deserialize(record: dict) -> dict:
    for key in ("suggested_signals", "validation_reasons", "metadata"):
        if isinstance(record.get(key), str):
            try:
                record[key] = json.loads(record[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return record
