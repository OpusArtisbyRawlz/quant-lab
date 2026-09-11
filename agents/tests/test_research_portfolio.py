"""
Phase 6 P6-9 — Research Portfolio persistence + lifecycle/state machine.

Proves the portfolio layer mirrors the campaign event-sourcing discipline exactly:
event-sourced state (the log is the source of truth), a rebuildable projection,
idempotent/replay-safe writes, the three approved states (ACTIVE/PAUSED/ARCHIVED)
with only their legal transitions, campaign membership through the existing
research_campaign.portfolio_id, and additive legacy-DB migration. The portfolio is a
planning container — it executes nothing and adds no scheduler/agent.
"""

from __future__ import annotations

import sqlite3

from agents.storage.db import (
    create_all_tables, get_connection, get_schema_version, SCHEMA_VERSION,
)
from agents.storage import portfolio_store as ps
from agents.storage.portfolio_store import (
    PORTFOLIO_ACTIVE, PORTFOLIO_PAUSED, PORTFOLIO_ARCHIVED,
)
from agents.campaign_manager import (
    CampaignManager, PortfolioError, is_legal_portfolio_transition,
)


def _db(tmp_path, name="pf.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _cm(db):
    return CampaignManager(db_path=db)


# --- create portfolio ------------------------------------------------------

def test_create_portfolio_starts_active(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    p = cm.create_portfolio(
        "P1", "Alpha", objective={"goal": "survive-clocks"},
        scheduling_policy="eig_weighted", concurrency_limit=3,
        budget_spec={"mode": "equal"}, stopping_spec={"all_complete": True},
    )
    assert p["state"] == PORTFOLIO_ACTIVE
    assert p["name"] == "Alpha"
    assert p["objective"] == {"goal": "survive-clocks"}
    assert p["scheduling_policy"] == "eig_weighted"
    assert p["concurrency_limit"] == 3
    assert p["budget_spec"] == {"mode": "equal"}
    assert p["stopping_spec"] == {"all_complete": True}
    assert cm.portfolio_state("P1") == PORTFOLIO_ACTIVE


def test_create_portfolio_defaults(tmp_path):
    db = _db(tmp_path)
    p = _cm(db).create_portfolio("P1", "Alpha")
    assert p["scheduling_policy"] == "priority"      # DEFAULT_SCHEDULING_POLICY
    assert p["concurrency_limit"] == 0               # unbounded
    assert p["objective"] is None


def test_duplicate_portfolio_rejected(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    with __import__("pytest").raises(PortfolioError):
        cm.create_portfolio("P1", "Again")


# --- legal state transitions ----------------------------------------------

def test_legal_transitions(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    assert cm.pause_portfolio("P1").to_state == PORTFOLIO_PAUSED
    assert cm.resume_portfolio("P1").to_state == PORTFOLIO_ACTIVE
    assert cm.archive_portfolio("P1").to_state == PORTFOLIO_ARCHIVED


def test_pause_then_archive_is_legal(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    cm.pause_portfolio("P1")
    assert cm.archive_portfolio("P1").to_state == PORTFOLIO_ARCHIVED


def test_transition_map_matches_design():
    # Exactly the approved states + transitions; ARCHIVED is terminal.
    assert is_legal_portfolio_transition(PORTFOLIO_ACTIVE, PORTFOLIO_PAUSED)
    assert is_legal_portfolio_transition(PORTFOLIO_ACTIVE, PORTFOLIO_ARCHIVED)
    assert is_legal_portfolio_transition(PORTFOLIO_PAUSED, PORTFOLIO_ACTIVE)
    assert is_legal_portfolio_transition(PORTFOLIO_PAUSED, PORTFOLIO_ARCHIVED)
    assert not is_legal_portfolio_transition(PORTFOLIO_ARCHIVED, PORTFOLIO_ACTIVE)
    assert not is_legal_portfolio_transition(PORTFOLIO_ARCHIVED, PORTFOLIO_PAUSED)


# --- illegal transition rejection -----------------------------------------

def test_illegal_transition_from_archived_rejected(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    cm.archive_portfolio("P1")
    import pytest
    with pytest.raises(PortfolioError):
        cm.resume_portfolio("P1")
    with pytest.raises(PortfolioError):
        cm.pause_portfolio("P1")
    # State is unchanged after a rejected transition.
    assert cm.portfolio_state("P1") == PORTFOLIO_ARCHIVED


def test_transition_unknown_portfolio_rejected(tmp_path):
    db = _db(tmp_path)
    import pytest
    with pytest.raises(PortfolioError):
        _cm(db).pause_portfolio("nope")


# --- reconstruction from event history ------------------------------------

def test_state_is_reconstructed_from_events(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    cm.pause_portfolio("P1")
    # The projection cache is only a cache; the log is the source of truth.
    ps.update_portfolio_state("P1", "GARBAGE", db_path=db)
    assert cm.portfolio_state("P1") == PORTFOLIO_PAUSED       # ignores the cache
    events = ps.list_portfolio_events("P1", db_path=db)
    assert [e["to_state"] for e in events] == [PORTFOLIO_ACTIVE, PORTFOLIO_PAUSED]


def test_rebuild_from_events_after_row_deleted(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", concurrency_limit=5,
                        scheduling_policy="round_robin")
    cm.pause_portfolio("P1")
    ps.delete_portfolio_row("P1", db_path=db)
    assert ps.get_portfolio("P1", db_path=db) is None
    rebuilt = cm.rebuild_portfolio_from_events("P1")
    assert rebuilt["state"] == PORTFOLIO_PAUSED
    assert rebuilt["concurrency_limit"] == 5
    assert rebuilt["scheduling_policy"] == "round_robin"


def test_reconcile_repairs_stale_cache(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    cm.pause_portfolio("P1")
    ps.update_portfolio_state("P1", "GARBAGE", db_path=db)
    report = cm.reconcile_portfolio("P1")
    assert report["repaired"] is True
    assert report["authoritative_state"] == PORTFOLIO_PAUSED
    assert ps.get_portfolio("P1", db_path=db)["state"] == PORTFOLIO_PAUSED


# --- idempotent writes -----------------------------------------------------

def test_same_state_transition_is_noop(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    r = cm.resume_portfolio("P1")                # already ACTIVE
    assert r.changed is False
    assert r.event_id is None
    assert len(ps.list_portfolio_events("P1", db_path=db)) == 1   # only genesis


def test_rebuild_is_idempotent(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    a = cm.rebuild_portfolio_from_events("P1")
    b = cm.rebuild_portfolio_from_events("P1")
    assert a["state"] == b["state"] == PORTFOLIO_ACTIVE
    # No duplicate rows, no extra events from rebuilding.
    assert len(ps.list_portfolios(db_path=db)) == 1
    assert len(ps.list_portfolio_events("P1", db_path=db)) == 1


# --- campaign association by portfolio_id ----------------------------------

def test_campaign_association_by_portfolio_id(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    cm.create_campaign("C2", theme="t", portfolio_id="P1")
    cm.create_campaign("C1", theme="t", portfolio_id="P1")
    cm.create_campaign("C_other", theme="t")     # standalone
    assert cm.campaigns_in_portfolio("P1") == ["C1", "C2"]   # sorted, deterministic


def test_empty_portfolio(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    assert cm.campaigns_in_portfolio("P1") == []


def test_multiple_campaigns_under_one_portfolio(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    for cid in ("Cc", "Ca", "Cb"):
        cm.create_campaign(cid, theme="t", portfolio_id="P1")
    assert cm.campaigns_in_portfolio("P1") == ["Ca", "Cb", "Cc"]


# --- replay determinism ----------------------------------------------------

def test_replay_determinism(tmp_path):
    def build(name):
        db = _db(tmp_path, name)
        cm = _cm(db)
        cm.create_portfolio("P1", "Alpha", concurrency_limit=2)
        cm.pause_portfolio("P1")
        cm.resume_portfolio("P1")
        cm.archive_portfolio("P1")
        return (
            cm.portfolio_state("P1"),
            [e["to_state"] for e in ps.list_portfolio_events("P1", db_path=db)],
        )
    assert build("a.db") == build("b.db")


# --- legacy DB migration ---------------------------------------------------

def test_legacy_db_gains_portfolio_tables(tmp_path):
    """A pre-P6-9 DB without the portfolio tables gains them on create_all_tables()."""
    db = tmp_path / "legacy.db"
    create_all_tables(db)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE research_portfolio")
        conn.execute("DROP TABLE portfolio_state_events")
        conn.commit()
    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "research_portfolio" not in tables

    create_all_tables(db)

    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"research_portfolio", "portfolio_state_events"} <= tables
    assert get_schema_version(db) == SCHEMA_VERSION
    # The rebuilt table is usable.
    _cm(db).create_portfolio("P1", "Alpha")
