"""
portfolio_store — Phase 6 P6-9 data-access for the research-portfolio tables.

A *research portfolio* is a lightweight planning container over member campaigns
(membership is ``research_campaign.portfolio_id``). Two tables back it, mirroring the
campaign layer exactly:

    portfolio_state_events   — append-only audit AND the SOURCE OF TRUTH for portfolio
                               state (sibling of campaign_state_events; carries no FK).
    research_portfolio       — a rebuildable *projection* of the event log: its
                               ``state`` is a cache of the latest event's to_state and
                               its config is carried in the genesis event.

This module is the low-level data-access layer only. All portfolio *state-machine*
logic (legal transitions, when to emit an event, reconstruction) lives in the
CampaignManager — the design assigns the portfolio state machine to that existing
coordinator, so no new agent is introduced. portfolio_store performs no transition
validation of its own; it just persists what it is told, append-only for events.

Nothing stored on the research_portfolio row is authoritative. The authoritative
state is ``reconstruct_portfolio_state_from_events()``; the row exists only so reads
need not replay the log, and it can be deleted and rebuilt at any point. The
portfolio holds no research logic and executes nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

# ---------------------------------------------------------------------------
# Portfolio state constants (exactly the three states in the approved design —
# §7. No others are invented.)
# ---------------------------------------------------------------------------

PORTFOLIO_ACTIVE = "ACTIVE"
PORTFOLIO_PAUSED = "PAUSED"
PORTFOLIO_ARCHIVED = "ARCHIVED"

ALL_PORTFOLIO_STATES = (PORTFOLIO_ACTIVE, PORTFOLIO_PAUSED, PORTFOLIO_ARCHIVED)

# ARCHIVED is terminal (a portfolio is dropped/rebuilt from membership, not revived).
PORTFOLIO_TERMINAL_STATES = (PORTFOLIO_ARCHIVED,)

# Scheduling policies (stored now; consumed by the P6-10 PortfolioPlanner).
POLICY_PRIORITY = "priority"
POLICY_ROUND_ROBIN = "round_robin"
POLICY_EIG_WEIGHTED = "eig_weighted"
DEFAULT_SCHEDULING_POLICY = POLICY_PRIORITY


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


_JSON_PORTFOLIO_FIELDS = ("objective", "budget_spec", "stopping_spec")


def _row_to_portfolio(row) -> dict[str, Any]:
    d = dict(row)
    for key in _JSON_PORTFOLIO_FIELDS:
        if key in d:
            d[key] = _loads(d[key])
    return d


# ---------------------------------------------------------------------------
# Portfolio writes (projection)
# ---------------------------------------------------------------------------

def insert_portfolio(portfolio: dict[str, Any], *, db_path: Path = DB_PATH) -> str:
    """Insert a research_portfolio projection row. Returns the portfolio_id.

    Expected keys: portfolio_id, name (required); optional objective,
    scheduling_policy, concurrency_limit, budget_spec, state, stopping_spec. JSON
    fields accept either a Python object or a pre-encoded string. Raises on a
    duplicate portfolio_id (PK).
    """
    portfolio_id = portfolio["portfolio_id"]
    now = _utcnow()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO research_portfolio (
                portfolio_id, name, objective, scheduling_policy,
                concurrency_limit, budget_spec, state, stopping_spec,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                portfolio["name"],
                _dumps(portfolio.get("objective")),
                portfolio.get("scheduling_policy", DEFAULT_SCHEDULING_POLICY),
                int(portfolio.get("concurrency_limit", 0)),
                _dumps(portfolio.get("budget_spec")),
                portfolio.get("state", PORTFOLIO_ACTIVE),
                _dumps(portfolio.get("stopping_spec")),
                now,
                now,
            ),
        )
        conn.commit()
    return portfolio_id


def update_portfolio_state(
    portfolio_id: str,
    new_state: str,
    *,
    db_path: Path = DB_PATH,
) -> None:
    """Set a portfolio's cached state and updated_at. Does not emit an event —
    callers pair this with append_portfolio_event for an auditable transition."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE research_portfolio SET state=?, updated_at=? WHERE portfolio_id=?",
            (new_state, _utcnow(), portfolio_id),
        )
        conn.commit()


def delete_portfolio_row(portfolio_id: str, *, db_path: Path = DB_PATH) -> None:
    """Delete only the research_portfolio projection row. The event log is left
    intact, so the row can be rebuilt via CampaignManager.rebuild_portfolio_from_events."""
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM research_portfolio WHERE portfolio_id=?", (portfolio_id,)
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Portfolio event log (append-only; source of truth)
# ---------------------------------------------------------------------------

def append_portfolio_event(
    portfolio_id: str,
    *,
    from_state: str | None,
    to_state: str,
    reason_code: str | None = None,
    evidence: Any = None,
    db_path: Path = DB_PATH,
) -> int:
    """Append an immutable portfolio_state_events row. Returns the new row id."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO portfolio_state_events (
                portfolio_id, from_state, to_state, reason_code, evidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (portfolio_id, from_state, to_state, reason_code, _dumps(evidence), _utcnow()),
        )
        conn.commit()
        return int(cur.lastrowid)


def reconstruct_portfolio_state_from_events(
    portfolio_id: str,
    *,
    db_path: Path = DB_PATH,
) -> str | None:
    """A portfolio's authoritative state, derived purely from its event log: the
    to_state of the most-recent event. None if the portfolio has no events (never
    existed). Never reads research_portfolio.state, so it is the canonical truth."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT to_state FROM portfolio_state_events WHERE portfolio_id=? "
            "ORDER BY id DESC LIMIT 1",
            (portfolio_id,),
        ).fetchone()
    return row["to_state"] if row else None


def portfolio_genesis_event(
    portfolio_id: str,
    *,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """The earliest (creation) event for a portfolio, whose evidence carries the
    full config needed to rebuild the projection row."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_state_events WHERE portfolio_id=? "
            "ORDER BY id ASC LIMIT 1",
            (portfolio_id,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["evidence"] = _loads(d.get("evidence"))
    return d


def list_portfolio_events(
    portfolio_id: str,
    *,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """The append-only transition history for a portfolio, oldest first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_state_events WHERE portfolio_id=? ORDER BY id",
            (portfolio_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["evidence"] = _loads(d.get("evidence"))
        out.append(d)
    return out


def distinct_portfolio_ids_in_events(*, db_path: Path = DB_PATH) -> list[str]:
    """Every portfolio_id in the event log, whether or not a projection row exists.
    Used by startup reconciliation."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT portfolio_id FROM portfolio_state_events "
            "ORDER BY portfolio_id"
        ).fetchall()
    return [r["portfolio_id"] for r in rows]


# ---------------------------------------------------------------------------
# Portfolio reads (projection)
# ---------------------------------------------------------------------------

def get_portfolio(portfolio_id: str, *, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM research_portfolio WHERE portfolio_id=?", (portfolio_id,)
        ).fetchone()
    return _row_to_portfolio(row) if row else None


def list_portfolios(
    *,
    state: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        if state is None:
            rows = conn.execute(
                "SELECT * FROM research_portfolio ORDER BY created_at, portfolio_id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM research_portfolio WHERE state=? "
                "ORDER BY created_at, portfolio_id",
                (state,),
            ).fetchall()
    return [_row_to_portfolio(r) for r in rows]


# ---------------------------------------------------------------------------
# Membership (campaign ↔ portfolio, via the existing research_campaign.portfolio_id)
# ---------------------------------------------------------------------------

def campaigns_in_portfolio(portfolio_id: str, *, db_path: Path = DB_PATH) -> list[str]:
    """Campaign ids whose ``portfolio_id`` links them to this portfolio, ordered by
    campaign_id (deterministic). Reads the existing P6-8 column — no new linkage."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT campaign_id FROM research_campaign WHERE portfolio_id=? "
            "ORDER BY campaign_id",
            (portfolio_id,),
        ).fetchall()
    return [r["campaign_id"] for r in rows]
