"""
Phase 6 P6-11 — trigger-aware planning (eligibility owned by CampaignManager).

Proves that trigger/dependency/repeat *evaluation* lives solely in the
CampaignManager (its pure `is_eligible` / `trigger_satisfied` / `repeat_eligible`
predicates), that the PortfolioPlanner obtains eligibility from it (no duplicated
trigger logic), and that the resulting plan stays deterministic and lifecycle-aware.

Scope (confirmed with reviewer): `manual` + `dependency` triggers and the `once`
+ `interval` (count-capped) repeat modes are evaluated now; `schedule`/`event`
triggers and interval-cooldown / `until` predicates are deferred (they need the
FactoryRunner logical-tick clock / a projection-predicate catalog). The planner
never fires transitions, mutates state, or consumes budget.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables
from agents.campaign_manager import (
    CampaignManager, CampaignError,
    TRIGGER_MANUAL, TRIGGER_DEPENDENCY, TRIGGER_SCHEDULE, TRIGGER_EVENT,
    REPEAT_ONCE, REPEAT_INTERVAL, REPEAT_UNTIL,
)
from agents.portfolio_planner import PortfolioPlanner


def _db(tmp_path, name="ta.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _cm(db):
    return CampaignManager(db_path=db)


def _active(cm, cid, portfolio_id=None, *, activate=True, **fields):
    cm.create_campaign(cid, theme="t", portfolio_id=portfolio_id, **fields)
    if activate:
        cm.activate(cid)


def _plan(db, pid):
    return PortfolioPlanner(db_path=db).plan(pid).admitted


# --- trigger satisfied / not satisfied (CampaignManager, the owner) ---------

def test_manual_trigger_satisfied_when_active(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "m")                                    # default kind = manual
    assert cm.trigger_satisfied("m") is True
    assert cm.is_eligible("m") is True


def test_dependency_trigger_not_satisfied_until_dep_complete(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "pre")
    _active(cm, "dep", trigger_spec={"kind": TRIGGER_DEPENDENCY}, depends_on=["pre"])
    assert cm.trigger_satisfied("dep") is False         # pre is ACTIVE, needs COMPLETED
    assert cm.is_eligible("dep") is False
    cm.complete("pre")
    assert cm.trigger_satisfied("dep") is True
    assert cm.is_eligible("dep") is True


def test_schedule_event_triggers_deferred_to_active(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "sched", trigger_spec={"kind": TRIGGER_SCHEDULE, "every_ticks": 3})
    _active(cm, "evt", trigger_spec={"kind": TRIGGER_EVENT, "on": "strategy_retired"})
    # Deferred kinds: activation counts (no auto-firing) ⇒ trigger-satisfied once ACTIVE.
    assert cm.trigger_satisfied("sched") is True
    assert cm.trigger_satisfied("evt") is True


def test_trigger_satisfied_unknown_campaign_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(CampaignError):
        _cm(db).trigger_satisfied("nope")


# --- repeat allowed / blocked (CampaignManager, the owner) -----------------

def test_repeat_once_blocked(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "c", repeat_spec={"mode": REPEAT_ONCE})
    cm.complete("c")
    assert cm.repeat_eligible("c") is False


def test_repeat_interval_allowed_under_cap(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "c", repeat_spec={"mode": REPEAT_INTERVAL, "max_repeats": 1})
    cm.complete("c")
    assert cm.repeat_eligible("c") is True


def test_repeat_interval_blocked_at_cap(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "c", repeat_spec={"mode": REPEAT_INTERVAL, "max_repeats": 0})
    cm.complete("c")
    assert cm.repeat_eligible("c") is False


def test_repeat_interval_unbounded_allowed(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "c", repeat_spec={"mode": REPEAT_INTERVAL})   # max_repeats null
    cm.complete("c")
    assert cm.repeat_eligible("c") is True


def test_repeat_until_deferred_blocked(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "c", repeat_spec={"mode": REPEAT_UNTIL, "predicate": "no_survivors"})
    cm.complete("c")
    assert cm.repeat_eligible("c") is False               # until predicate deferred


def test_repeat_not_eligible_before_completion(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _active(cm, "c", repeat_spec={"mode": REPEAT_INTERVAL, "max_repeats": 5})
    assert cm.repeat_eligible("c") is False               # still ACTIVE, not COMPLETED


# --- planner obtains eligibility from the owner ----------------------------

def test_planner_excludes_dependency_gated_campaign(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "pre", "P1", priority=1.0)
    _active(cm, "dep", "P1", priority=9.0,
            trigger_spec={"kind": TRIGGER_DEPENDENCY}, depends_on=["pre"])
    assert _plan(db, "P1") == ["pre"]                     # dep's trigger unsatisfied
    cm.complete("pre")
    assert _plan(db, "P1") == ["dep"]                     # pre no longer ACTIVE; dep runnable


def test_planner_matches_is_eligible(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "a", "P1", priority=2.0)
    _active(cm, "b", "P1", priority=1.0)
    _active(cm, "draft", "P1", activate=False)
    plan = _plan(db, "P1")
    for cid in plan:
        assert cm.is_eligible(cid)
    assert "draft" not in plan                            # not ACTIVE ⇒ not eligible


# --- dependency chains -----------------------------------------------------

def test_dependency_chain_admits_one_stage_at_a_time(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    # A → B → C, each gated on the previous COMPLETED.
    _active(cm, "A", "P1", priority=1.0)
    _active(cm, "B", "P1", priority=5.0,
            trigger_spec={"kind": TRIGGER_DEPENDENCY}, depends_on=["A"])
    _active(cm, "C", "P1", priority=9.0,
            trigger_spec={"kind": TRIGGER_DEPENDENCY}, depends_on=["B"])
    assert _plan(db, "P1") == ["A"]
    cm.complete("A")
    assert _plan(db, "P1") == ["B"]
    cm.complete("B")
    assert _plan(db, "P1") == ["C"]


def test_dependency_aware_ordering_among_co_runnable(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "pre", "P1", priority=1.0)
    _active(cm, "dep", "P1", priority=9.0,
            depends_on=[{"campaign_id": "pre", "required_state": "ACTIVE"}])
    # Both runnable (dep needs pre ACTIVE); prerequisite ordered first despite lower priority.
    assert _plan(db, "P1") == ["pre", "dep"]


# --- priority ordering (still the planner's job) ---------------------------

def test_priority_ordering_preserved(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "lo", "P1", priority=1.0)
    _active(cm, "hi", "P1", priority=5.0)
    _active(cm, "mid", "P1", priority=3.0)
    assert _plan(db, "P1") == ["hi", "mid", "lo"]


# --- lifecycle: archived / paused campaigns --------------------------------

def test_archived_and_stalled_campaigns_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "active", "P1", priority=1.0)
    _active(cm, "shelved", "P1", priority=8.0)
    _active(cm, "stalled", "P1", priority=9.0)
    cm.archive("shelved")
    cm.mark_stalled("stalled")
    assert _plan(db, "P1") == ["active"]
    assert cm.is_eligible("shelved") is False
    assert cm.is_eligible("stalled") is False


# --- multiple / empty portfolios -------------------------------------------

def test_multiple_portfolios_independent(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P_a", "A")
    cm.create_portfolio("P_b", "B")
    _active(cm, "a1", "P_a", priority=2.0)
    _active(cm, "a2", "P_a", priority=1.0)
    _active(cm, "b1", "P_b", priority=5.0)
    plans = {p.portfolio_id: p.admitted for p in PortfolioPlanner(db_path=db).plan_all()}
    assert plans == {"P_a": ["a1", "a2"], "P_b": ["b1"]}


def test_empty_portfolio_plans_empty(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    assert _plan(db, "P1") == []


# --- deterministic replay / identical output -------------------------------

def test_replay_determinism_identical_output(tmp_path):
    def build(name):
        db = _db(tmp_path, name)
        cm = _cm(db)
        cm.create_portfolio("P1", "Alpha", concurrency_limit=3)
        _active(cm, "pre", "P1", priority=1.0)
        _active(cm, "dep", "P1", priority=9.0,
                depends_on=[{"campaign_id": "pre", "required_state": "ACTIVE"}])
        _active(cm, "solo", "P1", priority=5.0)
        return _plan(db, "P1")
    assert build("r1.db") == build("r2.db")


def test_planning_is_pure_no_state_change(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "c", "P1", priority=1.0)
    before = cm.current_state("c")
    a = _plan(db, "P1")
    b = _plan(db, "P1")
    assert a == b == ["c"]
    assert cm.current_state("c") == before               # planner mutated nothing
