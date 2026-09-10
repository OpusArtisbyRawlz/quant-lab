"""
handoff_store — Phase 6 P6-4: the Project 07 hand-off boundary.

The Quant Research Factory's M11 output is **preliminary**. Project 07 —
Statistical Integrity — is the **authoritative** final evaluator. This module is
the neutral surface between them:

    pending_handoffs()   — DERIVED queue: campaigns the factory has COMPLETED that
                           Project 07 has not yet evaluated. Pure read; no new
                           write-path, no factory change. The factory produces work
                           to hand off simply by completing campaigns.

    record_evaluation()  — Project 07's write: upsert its authoritative verdict into
                           `project07_evaluation`. This is the ONLY writer of that
                           table. The factory never calls it.

    get_evaluation() / list_evaluations() — reads of Project 07's verdicts.

    evaluation_status()  — a campaign's position on the preliminary→authoritative
                           axis: in_progress (not yet completed), preliminary
                           (completed, awaiting Project 07), or authoritative
                           (Project 07 has ruled).

Isolation: this module imports only the campaign store and the DB layer. It does
NOT import Project 07 (the factory must not depend on the authoritative evaluator)
and has no Chrysos coupling whatsoever. The `verdict` payload is opaque here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH
from . import campaign_store
from .campaign_store import STATE_COMPLETED

# ---------------------------------------------------------------------------
# Evaluation-status axis (preliminary → authoritative)
# ---------------------------------------------------------------------------

# The campaign has not yet reached COMPLETED — nothing to hand off.
STATUS_IN_PROGRESS = "in_progress"
# COMPLETED by the factory, but Project 07 has not evaluated it yet. M11's
# evidence stands only as preliminary.
STATUS_PRELIMINARY = "preliminary"
# Project 07 has written an authoritative verdict.
STATUS_AUTHORITATIVE = "authoritative"


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _loads(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _evaluated_ids(db_path: Path = DB_PATH) -> set[str]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT campaign_id FROM project07_evaluation"
        ).fetchall()
    return {r["campaign_id"] for r in rows}


# ---------------------------------------------------------------------------
# Derived hand-off queue (the factory side — read only)
# ---------------------------------------------------------------------------

def pending_handoffs(*, db_path: Path = DB_PATH) -> list[str]:
    """Campaign_ids the factory has COMPLETED but Project 07 has not evaluated.

    Purely DERIVED — the set difference of (completed campaigns) − (evaluated
    campaigns). No queue is stored and nothing is mutated, so this is replay-safe
    and idempotent. Ordered by campaign_id for deterministic consumption.
    """
    completed = campaign_store.list_campaigns(state=STATE_COMPLETED, db_path=db_path)
    evaluated = _evaluated_ids(db_path)
    return sorted(
        c["campaign_id"] for c in completed if c["campaign_id"] not in evaluated
    )


# ---------------------------------------------------------------------------
# Project 07's write path (the authoritative side)
# ---------------------------------------------------------------------------

def record_evaluation(
    campaign_id: str,
    *,
    verdict: Any = None,
    method: str | None = None,
    status: str = STATUS_AUTHORITATIVE,
    db_path: Path = DB_PATH,
) -> None:
    """Project 07 records its authoritative verdict for a campaign (upsert).

    The sole writer of `project07_evaluation`. `verdict` is opaque to the factory
    (JSON-encoded here); `method` is Project 07's version/tag. Called by Project 07
    only — the factory never invokes this.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO project07_evaluation "
            "(campaign_id, verdict, status, method, evaluated_at) "
            "VALUES (?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(campaign_id) DO UPDATE SET "
            "verdict=excluded.verdict, status=excluded.status, "
            "method=excluded.method, evaluated_at=excluded.evaluated_at",
            (campaign_id, _dumps(verdict), status, method),
        )
        conn.commit()


def get_evaluation(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> dict[str, Any] | None:
    """Project 07's verdict for a campaign, or None if not yet evaluated."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM project07_evaluation WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["verdict"] = _loads(d.get("verdict"))
    return d


def list_evaluations(*, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """All Project 07 verdicts, ordered by campaign_id."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM project07_evaluation ORDER BY campaign_id"
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["verdict"] = _loads(d.get("verdict"))
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# The preliminary → authoritative axis
# ---------------------------------------------------------------------------

def evaluation_status(campaign_id: str, *, db_path: Path = DB_PATH) -> str:
    """Where a campaign sits on the evaluation axis.

    - STATUS_AUTHORITATIVE if Project 07 has recorded a verdict;
    - STATUS_PRELIMINARY if the factory has COMPLETED it but Project 07 has not;
    - STATUS_IN_PROGRESS otherwise (not yet completed — nothing to hand off).
    """
    if get_evaluation(campaign_id, db_path=db_path) is not None:
        return STATUS_AUTHORITATIVE
    state = campaign_store.reconstruct_state_from_events(campaign_id, db_path=db_path)
    if state == STATE_COMPLETED:
        return STATUS_PRELIMINARY
    return STATUS_IN_PROGRESS
