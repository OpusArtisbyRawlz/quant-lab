"""
campaign_store — reads and writes the Milestone 10 research-campaign tables.

A *research campaign* is a themed, budgeted, multi-experiment investigation. Two
tables back it:

    campaign_state_events   — append-only audit of every state transition AND the
                              SOURCE OF TRUTH for campaign state (mirrors
                              signal_lifecycle_events from M9; carries no FK).
    research_campaign       — a rebuildable *projection* of the event log: its
                              `state` is a cache of the latest event's to_state,
                              its config is carried in the genesis event, and its
                              `budget_spent` is a cache of campaign-tagged
                              experiment count.

This module is the low-level data-access layer. All campaign *state-machine*
logic (which transitions are legal, when to emit an event, reconciliation,
progress derivation) lives in the CampaignManager agent, which is the sole
writer of these tables. campaign_store performs no transition validation of its
own — it just persists what it is told, append-only for events.

Nothing stored on the research_campaign row is authoritative. The authoritative
state is `reconstruct_state_from_events()`; the authoritative progress is
`count_campaign_experiments()`. The row exists only so reads do not have to
replay the log every time, and it can be deleted and rebuilt at any point.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

# ---------------------------------------------------------------------------
# Campaign state constants
# ---------------------------------------------------------------------------

STATE_DRAFT = "DRAFT"
STATE_ACTIVE = "ACTIVE"
STATE_STALLED = "STALLED"
STATE_COMPLETED = "COMPLETED"
STATE_ARCHIVED = "ARCHIVED"
STATE_DISCARDED = "DISCARDED"

ALL_STATES = (
    STATE_DRAFT,
    STATE_ACTIVE,
    STATE_STALLED,
    STATE_COMPLETED,
    STATE_ARCHIVED,
    STATE_DISCARDED,
)

# Terminal states never transition out.
TERMINAL_STATES = (STATE_COMPLETED, STATE_ARCHIVED, STATE_DISCARDED)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str | None:
    """JSON-encode a dict/list; pass through None and pre-encoded strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _row_to_campaign(row) -> dict[str, Any]:
    d = dict(row)
    for key in ("goal_spec", "scope", "stopping_spec"):
        if key in d:
            d[key] = _loads(d[key])
    return d


# ---------------------------------------------------------------------------
# Campaign writes
# ---------------------------------------------------------------------------

def insert_campaign(
    campaign: dict[str, Any],
    *,
    db_path: Path = DB_PATH,
) -> str:
    """Insert a new research_campaign row. Returns the campaign_id.

    Expected keys: campaign_id, theme (required); optional goal_spec, scope,
    state, budget_experiments, exploration_fraction, stall_patience,
    stopping_spec. JSON-typed fields accept either a Python object or a
    pre-encoded string. Raises on duplicate campaign_id (PK).
    """
    campaign_id = campaign["campaign_id"]
    now = _utcnow()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO research_campaign (
                campaign_id, theme, goal_spec, scope, state,
                budget_experiments, budget_spent, exploration_fraction,
                stall_patience, stopping_spec, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                campaign["theme"],
                _dumps(campaign.get("goal_spec")),
                _dumps(campaign.get("scope")),
                campaign.get("state", STATE_DRAFT),
                int(campaign.get("budget_experiments", 0)),
                int(campaign.get("budget_spent", 0)),
                float(campaign.get("exploration_fraction", 0.34)),
                int(campaign.get("stall_patience", 3)),
                _dumps(campaign.get("stopping_spec")),
                now,
                now,
            ),
        )
        conn.commit()
    return campaign_id


def update_campaign_state(
    campaign_id: str,
    new_state: str,
    *,
    completed_at: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Set a campaign's cached state and updated_at. Optionally stamp
    completed_at (for terminal states). Does not emit an event — callers should
    pair this with append_state_event for an auditable transition."""
    now = _utcnow()
    with get_connection(db_path) as conn:
        if completed_at is not None:
            conn.execute(
                "UPDATE research_campaign SET state=?, updated_at=?, completed_at=? "
                "WHERE campaign_id=?",
                (new_state, now, completed_at, campaign_id),
            )
        else:
            conn.execute(
                "UPDATE research_campaign SET state=?, updated_at=? WHERE campaign_id=?",
                (new_state, now, campaign_id),
            )
        conn.commit()


def set_budget_spent(
    campaign_id: str,
    budget_spent: int,
    *,
    db_path: Path = DB_PATH,
) -> None:
    """Refresh the cached budget_spent counter (canonical value is derivable)."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE research_campaign SET budget_spent=?, updated_at=? WHERE campaign_id=?",
            (int(budget_spent), _utcnow(), campaign_id),
        )
        conn.commit()


def append_state_event(
    campaign_id: str,
    *,
    from_state: str | None,
    to_state: str,
    reason_code: str | None = None,
    evidence: Any = None,
    db_path: Path = DB_PATH,
) -> int:
    """Append an immutable campaign_state_events row. Returns the new row id."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO campaign_state_events (
                campaign_id, from_state, to_state, reason_code, evidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                from_state,
                to_state,
                reason_code,
                _dumps(evidence),
                _utcnow(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Campaign reads
# ---------------------------------------------------------------------------

def get_campaign(
    campaign_id: str,
    *,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM research_campaign WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
    return _row_to_campaign(row) if row else None


def list_campaigns(
    *,
    state: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        if state is None:
            rows = conn.execute(
                "SELECT * FROM research_campaign ORDER BY created_at"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM research_campaign WHERE state=? ORDER BY created_at",
                (state,),
            ).fetchall()
    return [_row_to_campaign(r) for r in rows]


def list_state_events(
    campaign_id: str,
    *,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Return the append-only transition history for a campaign, oldest first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM campaign_state_events WHERE campaign_id=? "
            "ORDER BY id",
            (campaign_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["evidence"] = _loads(d.get("evidence"))
        out.append(d)
    return out


def link_idea_to_campaign(
    idea_id: str,
    campaign_id: str,
    *,
    db_path: Path = DB_PATH,
) -> bool:
    """Tag an existing pending idea with its originating campaign (write-once
    attribution). Sets ``pending_ideas.campaign_id`` only if it is currently
    NULL, so an idea's campaign attribution is never silently re-pointed. Returns
    True if the tag was applied, False if the idea was already tagged or absent.

    This writes only the additive attribution column added in M10 PR-1; it does
    not touch the approval state machine, validation, or any execution field.
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE pending_ideas SET campaign_id = ? "
            "WHERE idea_id = ? AND campaign_id IS NULL",
            (campaign_id, idea_id),
        )
        conn.commit()
        return cur.rowcount > 0


def campaign_id_for_idea(
    idea_id: str,
    *,
    db_path: Path = DB_PATH,
) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT campaign_id FROM pending_ideas WHERE idea_id = ?", (idea_id,)
        ).fetchone()
    return row["campaign_id"] if row else None


def reconstruct_state_from_events(
    campaign_id: str,
    *,
    db_path: Path = DB_PATH,
) -> str | None:
    """Return a campaign's authoritative state, derived purely from its event
    log: the to_state of the most-recent event. Returns None if the campaign has
    no events (i.e. it never existed). This never reads research_campaign.state,
    so it is the canonical source of truth for campaign state."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT to_state FROM campaign_state_events WHERE campaign_id=? "
            "ORDER BY id DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
    return row["to_state"] if row else None


def genesis_event(
    campaign_id: str,
    *,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Return the earliest (creation) event for a campaign, whose evidence
    carries the full campaign config needed to rebuild the projection row."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM campaign_state_events WHERE campaign_id=? "
            "ORDER BY id ASC LIMIT 1",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["evidence"] = _loads(d.get("evidence"))
    return d


def distinct_campaign_ids_in_events(
    *,
    db_path: Path = DB_PATH,
) -> list[str]:
    """Every campaign_id that appears in the event log, regardless of whether a
    projection row currently exists. Used by startup reconciliation."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT campaign_id FROM campaign_state_events ORDER BY campaign_id"
        ).fetchall()
    return [r["campaign_id"] for r in rows]


def delete_campaign_row(
    campaign_id: str,
    *,
    db_path: Path = DB_PATH,
) -> None:
    """Delete only the research_campaign projection row. The event log is left
    intact, so the row can be rebuilt via CampaignManager.rebuild_from_events.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM research_campaign WHERE campaign_id=?", (campaign_id,)
        )
        conn.commit()


def count_campaign_experiments(
    campaign_id: str,
    *,
    db_path: Path = DB_PATH,
) -> int:
    """Derive how many experiments a campaign has produced, by counting
    completed experiments linked through campaign-tagged ideas. This is the
    canonical progress measure; budget_spent on the campaign row is only a
    cache of this value."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM pending_ideas
            WHERE campaign_id = ?
              AND experiment_id IS NOT NULL
              AND experiment_id != ''
            """,
            (campaign_id,),
        ).fetchone()
    return int(row["n"]) if row else 0
