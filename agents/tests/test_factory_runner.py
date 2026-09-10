"""
Phase 6 P6-3 — FactoryRunner (thin, stateless, resumable driver) + CampaignManager.advance.

Proves the driver discovers runnable campaigns via the existing scheduler, ticks
them in deterministic order via the existing ResearchLoop, delegates stop-condition
transitions to CampaignManager, is bounded/terminating, and resumes without
duplicating completed ticks — reusing all existing persistence/checkpoint logic and
holding no state of its own.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.campaign_manager import CampaignManager
from agents.campaign_manager.manager import (
    STATE_ACTIVE, STATE_COMPLETED, STATE_DRAFT, STATE_STALLED,
)
from agents.research_loop.loop import LoopConfig
from agents.research_loop.factory_runner import FactoryRunner, FactoryReport


def _db(tmp_path, name="f.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


_SEQ = [0]


def _spent(db, campaign_id):
    """Give a campaign one completed experiment (via a campaign-tagged idea) so
    it counts as one unit of budget spent. Each call is a distinct idea/experiment."""
    _SEQ[0] += 1
    k = _SEQ[0]
    with get_connection(db) as c:
        c.execute(
            "INSERT INTO pending_ideas (idea_id, hypothesis, suggested_signals, "
            " source_model, status, validation_ok, campaign_id, experiment_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (f"i-{campaign_id}-{k}", "h", "[]", "m", "executed", 1, campaign_id, f"E-{campaign_id}-{k}"),
        )
        c.commit()


def _active(cm, cid, priority, **kw):
    cm.create_campaign(cid, theme="t", goal_spec={"priority": priority}, **kw)
    cm.activate(cid)


def _runner(db):
    return FactoryRunner(db_path=db, loop_config=LoopConfig(generate=False))


# --- discovery + deterministic order --------------------------------------

def test_ticks_runnable_campaigns_in_priority_order(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _active(cm, "C_lo", 1)
    _active(cm, "C_hi", 5)
    rep = _runner(db).run(max_ticks=4)
    assert rep.ticked == ["C_hi", "C_lo", "C_hi", "C_lo"]     # round-robin, priority-first
    assert rep.stop_reason == "max_ticks"


def test_order_is_creation_order_independent(tmp_path):
    def run(order, name):
        db = _db(tmp_path, name)
        cm = CampaignManager(db_path=db)
        for cid, pri in order:
            _active(cm, cid, pri)
        return _runner(db).run(max_ticks=4).ticked

    assert run([("A", 1), ("B", 9), ("C", 5)], "a.db") == \
        run([("C", 5), ("A", 1), ("B", 9)], "b.db") == ["B", "C", "A", "B"]


def test_empty_factory_stops_immediately(tmp_path):
    rep = _runner(_db(tmp_path)).run(max_ticks=5)
    assert rep.ticks == 0 and rep.ticked == []
    assert rep.stop_reason == "no_runnable_campaigns"


# --- stop conditions delegated to CampaignManager.advance -----------------

def test_pre_exhausted_campaign_is_completed(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _active(cm, "C_bud", 9, budget_experiments=1)
    _spent(db, "C_bud")                       # already at budget before any tick
    _active(cm, "C_go", 1)                     # an unbounded one to keep the loop alive
    _runner(db).run(max_ticks=2)
    assert cm.current_state("C_bud") == STATE_COMPLETED   # advanced without ticking
    assert "C_bud" not in _runner(db)._runnable_ids()     # excluded from runnable


def test_draft_campaign_is_not_force_completed(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("C_draft", theme="t", goal_spec={"priority": 1}, budget_experiments=1)
    _spent(db, "C_draft")                     # exhausted but never activated
    _active(cm, "C_go", 2)
    _runner(db).run(max_ticks=1)
    assert cm.current_state("C_draft") == STATE_DRAFT      # illegal DRAFT→COMPLETED not taken


def test_advance_only_completes_active_or_stalled_when_exhausted(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _active(cm, "C", 1, budget_experiments=2)
    assert cm.advance("C") == STATE_ACTIVE                 # not exhausted → unchanged
    _spent(db, "C"); _spent(db, "C")
    assert cm.advance("C") == STATE_COMPLETED              # exhausted → completed
    assert cm.advance("C") == STATE_COMPLETED              # idempotent on terminal


# --- bounds ---------------------------------------------------------------

def test_max_rounds_bound(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _active(cm, "A", 1)
    _active(cm, "B", 2)
    rep = _runner(db).run(max_rounds=2)
    assert rep.rounds == 2 and rep.ticks == 4 and rep.stop_reason == "max_rounds"


# --- resume / no duplicated execution -------------------------------------

def _tick_ids(db):
    with get_connection(db) as c:
        return {r["tick_id"] for r in c.execute(
            "SELECT DISTINCT tick_id FROM loop_checkpoint").fetchall()}


def test_restart_continues_without_re_running_completed_ticks(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _active(cm, "A", 1)
    _runner(db).run(max_ticks=2)              # first driver
    first = _tick_ids(db)
    assert len(first) == 2

    _runner(db).run(max_ticks=2)              # a fresh driver on the same DB (restart)
    second = _tick_ids(db)
    # The earlier completed ticks persist unchanged; the restart adds NEW ticks —
    # no completed tick is re-executed.
    assert first <= second
    assert len(second) == 4


def test_runner_is_stateless_no_new_tables(tmp_path):
    # The FactoryRunner persists nothing of its own; state lives in existing stores.
    db = _db(tmp_path)
    before = _table_names(db)
    cm = CampaignManager(db_path=db)
    _active(cm, "A", 1)
    _runner(db).run(max_ticks=1)
    assert _table_names(db) == before


def _table_names(db):
    with get_connection(db) as c:
        return {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


# --- report ---------------------------------------------------------------

def test_report_as_dict(tmp_path):
    db = _db(tmp_path)
    CampaignManager(db_path=db)  # no campaigns
    rep = _runner(db).run(max_ticks=1)
    assert rep.as_dict() == {"ticks": 0, "ticked": [], "rounds": 0,
                             "stop_reason": "no_runnable_campaigns"}
