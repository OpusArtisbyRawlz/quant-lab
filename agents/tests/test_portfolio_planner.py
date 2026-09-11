"""
Phase 6 P6-10 — PortfolioPlanner (pure, deterministic planning).

Proves the planner produces a deterministic execution plan from stored state only:
it reads ACTIVE portfolios + their member campaigns, filters to the runnable set
(ACTIVE, not budget-exhausted, dependencies satisfied), orders by the portfolio's
policy over the P6-8 fields (priority; eig_weighted = static priority then dynamic
EIG; round_robin deferred → priority fallback), refines that order to be
dependency-aware, and admits up to concurrency_limit. It executes nothing, mutates
no state, allocates no budget, and does not touch the scheduler/runner.
"""

from __future__ import annotations

from agents.storage.db import create_all_tables
from agents.campaign_manager import CampaignManager
from agents.portfolio_planner import PortfolioPlanner, PortfolioPlan


def _db(tmp_path, name="pp.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _cm(db):
    return CampaignManager(db_path=db)


def _active_campaign(cm, cid, portfolio_id=None, *, activate=True, **fields):
    cm.create_campaign(cid, theme="t", portfolio_id=portfolio_id, **fields)
    if activate:
        cm.activate(cid)


def _plan(db, pid):
    return PortfolioPlanner(db_path=db).plan(pid).admitted


# --- single portfolio, priority ordering -----------------------------------

def test_single_portfolio_priority_order(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")             # default policy = priority
    _active_campaign(cm, "C_lo", "P1", priority=1.0)
    _active_campaign(cm, "C_hi", "P1", priority=5.0)
    _active_campaign(cm, "C_mid", "P1", priority=3.0)
    assert _plan(db, "P1") == ["C_hi", "C_mid", "C_lo"]


def test_equal_priority_breaks_on_campaign_id(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "C_b", "P1", priority=2.0)
    _active_campaign(cm, "C_a", "P1", priority=2.0)
    _active_campaign(cm, "C_c", "P1", priority=2.0)
    assert _plan(db, "P1") == ["C_a", "C_b", "C_c"]    # stable, deterministic


def test_priority_falls_back_to_goal_spec(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "C_col", "P1", priority=1.0)              # explicit column
    _active_campaign(cm, "C_goal", "P1", goal_spec={"priority": 9})  # legacy fallback
    assert _plan(db, "P1") == ["C_goal", "C_col"]


# --- eig_weighted ----------------------------------------------------------

def test_eig_weighted_priority_then_eig(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", scheduling_policy="eig_weighted")
    _active_campaign(cm, "C_p3_e1", "P1", priority=3.0, expected_information_gain=1.0)
    _active_campaign(cm, "C_p3_e9", "P1", priority=3.0, expected_information_gain=9.0)
    _active_campaign(cm, "C_p1_e9", "P1", priority=1.0, expected_information_gain=9.0)
    # static priority dominates; EIG breaks ties within equal priority.
    assert _plan(db, "P1") == ["C_p3_e9", "C_p3_e1", "C_p1_e9"]


def test_eig_weighted_missing_eig_is_zero(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", scheduling_policy="eig_weighted")
    _active_campaign(cm, "C_has", "P1", priority=2.0, expected_information_gain=4.0)
    _active_campaign(cm, "C_none", "P1", priority=2.0)     # EIG absent ⇒ 0.0
    assert _plan(db, "P1") == ["C_has", "C_none"]


# --- round_robin deferral --------------------------------------------------

def test_round_robin_falls_back_to_priority(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", scheduling_policy="round_robin")
    _active_campaign(cm, "C_lo", "P1", priority=1.0)
    _active_campaign(cm, "C_hi", "P1", priority=5.0)
    # Deferred (no logical-tick cursor yet) ⇒ deterministic priority ordering.
    assert _plan(db, "P1") == ["C_hi", "C_lo"]


# --- concurrency limit -----------------------------------------------------

def test_concurrency_limit_truncates(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", concurrency_limit=2)
    _active_campaign(cm, "C1", "P1", priority=1.0)
    _active_campaign(cm, "C2", "P1", priority=2.0)
    _active_campaign(cm, "C3", "P1", priority=3.0)
    assert _plan(db, "P1") == ["C3", "C2"]


def test_zero_limit_is_unbounded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", concurrency_limit=0)
    for i in range(4):
        _active_campaign(cm, f"C{i}", "P1", priority=float(i))
    assert len(_plan(db, "P1")) == 4


# --- dependency ordering / filtering ---------------------------------------

def test_dependency_unsatisfied_excludes_dependent(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "pre", "P1", priority=1.0)
    _active_campaign(cm, "dep", "P1", priority=9.0, depends_on=["pre"])  # needs pre COMPLETED
    # dep is highest priority but its dependency (pre COMPLETED) is unsatisfied.
    assert _plan(db, "P1") == ["pre"]


def test_dependency_satisfied_admits_dependent(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "pre", "P1", priority=1.0)
    _active_campaign(cm, "dep", "P1", priority=9.0, depends_on=["pre"])
    cm.complete("pre")                                  # pre now COMPLETED
    assert _plan(db, "P1") == ["dep"]                   # pre no longer ACTIVE; dep runnable


def test_dependency_aware_ordering_among_runnable(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    # dep requires pre ACTIVE (satisfied while both runnable) → pre must precede dep,
    # even though dep has higher priority.
    _active_campaign(cm, "pre", "P1", priority=1.0)
    _active_campaign(cm, "dep", "P1", priority=9.0,
                     depends_on=[{"campaign_id": "pre", "required_state": "ACTIVE"}])
    assert _plan(db, "P1") == ["pre", "dep"]


def test_dependency_dict_form_default_required_state(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "pre", "P1", priority=1.0)
    _active_campaign(cm, "dep", "P1", priority=9.0,
                     depends_on=[{"campaign_id": "pre"}])   # default required_state COMPLETED
    assert _plan(db, "P1") == ["pre"]                       # unsatisfied → dep excluded


# --- trigger filtering (state-based) / lifecycle respect -------------------

def test_draft_campaign_not_runnable(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "active", "P1", priority=1.0)
    _active_campaign(cm, "draft", "P1", priority=9.0, activate=False)   # trigger not fired
    assert _plan(db, "P1") == ["active"]


def test_paused_campaign_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "active", "P1", priority=1.0)
    _active_campaign(cm, "stalled", "P1", priority=9.0)
    cm.mark_stalled("stalled")                          # STALLED ⇒ not ACTIVE ⇒ excluded
    assert _plan(db, "P1") == ["active"]


def test_completed_campaign_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "active", "P1", priority=1.0)
    _active_campaign(cm, "done", "P1", priority=9.0)
    cm.complete("done")
    assert _plan(db, "P1") == ["active"]


def test_archived_campaign_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "active", "P1", priority=1.0)
    _active_campaign(cm, "shelved", "P1", priority=9.0)
    cm.archive("shelved")
    assert _plan(db, "P1") == ["active"]


def test_repeat_spec_does_not_change_plan(tmp_path):
    """repeat_spec is owned by the CampaignManager (P6-11); the planner reads it
    only via state. A COMPLETED repeating campaign is not runnable here."""
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "standing", "P1", priority=9.0,
                     repeat_spec={"mode": "interval", "cooldown": 2})
    cm.complete("standing")                             # COMPLETED ⇒ excluded until re-entry
    assert _plan(db, "P1") == []


# --- portfolio state respect -----------------------------------------------

def test_paused_portfolio_admits_nothing(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "C1", "P1", priority=1.0)
    cm.pause_portfolio("P1")
    assert _plan(db, "P1") == []


def test_archived_portfolio_admits_nothing(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "C1", "P1", priority=1.0)
    cm.archive_portfolio("P1")
    assert _plan(db, "P1") == []


def test_unknown_portfolio_is_empty_plan(tmp_path):
    db = _db(tmp_path)
    assert _plan(db, "nope") == []


def test_empty_portfolio(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    plan = PortfolioPlanner(db_path=db).plan("P1")
    assert isinstance(plan, PortfolioPlan)
    assert plan.admitted == []


# --- multiple portfolios ---------------------------------------------------

def test_multiple_portfolios_isolated_and_ordered(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P_b", "Beta")
    cm.create_portfolio("P_a", "Alpha")
    _active_campaign(cm, "a1", "P_a", priority=1.0)
    _active_campaign(cm, "a2", "P_a", priority=2.0)
    _active_campaign(cm, "b1", "P_b", priority=5.0)
    cm.create_portfolio("P_paused", "Gamma")
    _active_campaign(cm, "g1", "P_paused", priority=9.0)
    cm.pause_portfolio("P_paused")

    plans = PortfolioPlanner(db_path=db).plan_all()
    # Only ACTIVE portfolios, ordered by portfolio_id; each plans independently.
    assert [p.portfolio_id for p in plans] == ["P_a", "P_b"]
    assert plans[0].admitted == ["a2", "a1"]
    assert plans[1].admitted == ["b1"]


def test_standalone_campaigns_ignored(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "member", "P1", priority=1.0)
    _active_campaign(cm, "standalone", None, priority=9.0)   # no portfolio_id
    assert _plan(db, "P1") == ["member"]
    assert all("standalone" not in p.admitted
               for p in PortfolioPlanner(db_path=db).plan_all())


# --- determinism / replay --------------------------------------------------

def test_replay_determinism_identical_output(tmp_path):
    def build(name):
        db = _db(tmp_path, name)
        cm = _cm(db)
        cm.create_portfolio("P1", "Alpha", scheduling_policy="eig_weighted",
                            concurrency_limit=3)
        _active_campaign(cm, "c_c", "P1", priority=2.0, expected_information_gain=1.0)
        _active_campaign(cm, "c_a", "P1", priority=2.0, expected_information_gain=5.0)
        _active_campaign(cm, "c_b", "P1", priority=3.0)
        _active_campaign(cm, "c_d", "P1", priority=3.0,
                         depends_on=[{"campaign_id": "c_b", "required_state": "ACTIVE"}])
        return PortfolioPlanner(db_path=db).plan("P1").admitted
    assert build("r1.db") == build("r2.db")


def test_plan_is_pure_no_mutation(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "C1", "P1", priority=1.0)
    planner = PortfolioPlanner(db_path=db)
    before_state = cm.current_state("C1")
    before_events = len(__import__("agents.storage.campaign_store",
                                   fromlist=["list_state_events"]).list_state_events(
        "C1", db_path=db))
    a = planner.plan("P1").admitted
    b = planner.plan("P1").admitted
    # Repeated planning is identical and changes nothing.
    assert a == b == ["C1"]
    assert cm.current_state("C1") == before_state
    assert len(__import__("agents.storage.campaign_store",
                          fromlist=["list_state_events"]).list_state_events(
        "C1", db_path=db)) == before_events


# --- legacy compatibility --------------------------------------------------

def test_legacy_campaign_without_extended_fields_plans(tmp_path):
    """A campaign created the old way (no P6-8 fields, priority in goal_spec) still
    plans deterministically — the planner reads through the effective accessors."""
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active_campaign(cm, "legacy_hi", "P1", goal_spec={"priority": 7})
    _active_campaign(cm, "legacy_lo", "P1", goal_spec={"priority": 2})
    assert _plan(db, "P1") == ["legacy_hi", "legacy_lo"]
