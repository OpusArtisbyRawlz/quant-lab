"""
Phase 6 P6-13 — deterministic portfolio-level budget allocation.

Proves the PortfolioPlanner deterministically splits a portfolio's window budget
across its admitted campaigns (design §9) by *reusing the frozen M11 budget
allocator* (water-filling + a_max anti-monopoly ceiling + integer floor) — no budget
logic duplicated, no scoring invented. Allocation respects the portfolio total, the
per-campaign a_max ceiling, and each campaign's own budget_experiments cap; ineligible
/ paused / archived / cyclic campaigns get nothing; unused budget is explicit
headroom; and everything is pure, deterministic, and replay/rebuild-stable.
"""

from __future__ import annotations

from agents.storage.db import create_all_tables
from agents.campaign_manager import CampaignManager
from agents.portfolio_planner import PortfolioPlanner, BudgetAllocation


def _db(tmp_path, name="pb.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _cm(db):
    return CampaignManager(db_path=db)


def _active(cm, cid, portfolio_id, *, activate=True, **fields):
    cm.create_campaign(cid, theme="t", portfolio_id=portfolio_id, **fields)
    if activate:
        cm.activate(cid)


def _alloc(db, pid):
    return PortfolioPlanner(db_path=db).allocate_budget(pid)


# --- one campaign / one portfolio ------------------------------------------

def test_single_campaign_uncapped_gets_full_budget(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "equal", "a_max": 1.0})
    _active(cm, "solo", "P1", priority=1.0)
    a = _alloc(db, "P1")
    assert isinstance(a, BudgetAllocation)
    assert a.allocations == {"solo": 20}
    assert a.headroom == 0


def test_single_campaign_default_a_max_leaves_headroom(tmp_path):
    """With the M11 default a_max=0.25 ceiling, a lone campaign cannot monopolise —
    the rest is explicit headroom (anti-monopoly, §9)."""
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", budget_spec={"total": 20, "mode": "equal"})
    _active(cm, "solo", "P1", priority=1.0)
    a = _alloc(db, "P1")
    assert a.allocations == {"solo": 5}          # floor(0.25 * 20)
    assert a.headroom == 15


# --- multiple campaigns -----------------------------------------------------

def test_equal_mode_splits_evenly(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", budget_spec={"total": 20, "mode": "equal"})
    for i in range(4):
        _active(cm, f"C{i}", "P1", priority=1.0)
    a = _alloc(db, "P1")
    assert a.allocations == {"C0": 5, "C1": 5, "C2": 5, "C3": 5}
    assert a.headroom == 0


def test_priority_proportional(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "priority_proportional",
                                     "a_max": 1.0})
    _active(cm, "lo", "P1", priority=1.0)
    _active(cm, "hi", "P1", priority=3.0)
    a = _alloc(db, "P1")
    assert a.allocations == {"hi": 15, "lo": 5}   # 3:1 share of 20
    assert a.headroom == 0


def test_eig_proportional_uses_cached_eig(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "eig_proportional",
                                     "a_max": 1.0})
    _active(cm, "lo", "P1", priority=1.0, expected_information_gain=1.0)
    _active(cm, "hi", "P1", priority=1.0, expected_information_gain=3.0)
    a = _alloc(db, "P1")
    assert a.allocations == {"hi": 15, "lo": 5}


def test_eig_proportional_degrades_to_uniform_before_p6_14(tmp_path):
    """Until P6-14 populates expected_information_gain, all weights are 0 ⇒ the M11
    allocator's 'no signal → uniform' path ⇒ equal split. P6-13 never aggregates raw
    EVOI itself."""
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "eig_proportional",
                                     "a_max": 1.0})
    _active(cm, "a", "P1", priority=1.0)          # no EIG set ⇒ 0
    _active(cm, "b", "P1", priority=9.0)          # priority ignored in eig mode
    a = _alloc(db, "P1")
    assert a.allocations == {"a": 10, "b": 10}


# --- campaign caps / portfolio cap -----------------------------------------

def test_campaign_cap_clamps_and_frees_headroom(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "equal", "a_max": 1.0})
    _active(cm, "capped", "P1", priority=1.0, budget_experiments=3)   # own cap 3
    _active(cm, "free", "P1", priority=1.0)                            # unbounded
    a = _alloc(db, "P1")
    # Even split is 10/10; capped campaign clamped to 3; freed 7 → headroom (not reflowed).
    assert a.allocations == {"capped": 3, "free": 10}
    assert a.headroom == 7


def test_portfolio_a_max_ceiling_caps_each_campaign(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "priority_proportional",
                                     "a_max": 0.5})
    _active(cm, "hog", "P1", priority=100.0)     # would take all, but ceiling = 0.5
    _active(cm, "small", "P1", priority=1.0)
    a = _alloc(db, "P1")
    assert a.allocations["hog"] == 10            # floor(0.5 * 20) ceiling
    assert a.headroom >= 0


# --- insufficient / zero budget --------------------------------------------

def test_zero_total_allocates_nothing(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", budget_spec={"total": 0, "mode": "equal"})
    _active(cm, "c", "P1", priority=1.0)
    a = _alloc(db, "P1")
    assert a.allocations == {}
    assert a.headroom == 0


def test_no_budget_spec_allocates_nothing(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")           # no budget_spec
    _active(cm, "c", "P1", priority=1.0)
    a = _alloc(db, "P1")
    assert a.allocations == {}
    assert a.headroom == 0


def test_insufficient_budget_floors_to_headroom(tmp_path):
    """A tiny window under many campaigns: a_min shares floor to 0 ⇒ the budget is
    left as headroom rather than fabricating fractional slots."""
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", budget_spec={"total": 1, "mode": "equal"})
    for i in range(4):
        _active(cm, f"C{i}", "P1", priority=1.0)
    a = _alloc(db, "P1")
    assert sum(a.allocations.values()) + a.headroom == 1
    assert a.headroom >= 0


# --- ineligible / lifecycle / cyclic get zero ------------------------------

def test_ineligible_and_lifecycle_campaigns_get_zero(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "equal", "a_max": 1.0})
    _active(cm, "active", "P1", priority=1.0)
    _active(cm, "draft", "P1", priority=1.0, activate=False)
    _active(cm, "shelved", "P1", priority=1.0)
    _active(cm, "stalled", "P1", priority=1.0)
    cm.archive("shelved")
    cm.mark_stalled("stalled")
    a = _alloc(db, "P1")
    assert a.allocations == {"active": 20}        # only the admitted campaign
    for cid in ("draft", "shelved", "stalled"):
        assert cid not in a.allocations


def test_cyclic_campaign_gets_zero(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "equal", "a_max": 1.0})
    _active(cm, "A", "P1", priority=1.0,
            depends_on=[{"campaign_id": "B", "required_state": "ACTIVE"}])
    _active(cm, "B", "P1", priority=1.0,
            depends_on=[{"campaign_id": "A", "required_state": "ACTIVE"}])
    _active(cm, "C", "P1", priority=1.0)          # independent, admitted
    a = _alloc(db, "P1")
    assert a.allocations == {"C": 20}             # cyclic A,B excluded ⇒ zero
    assert "A" not in a.allocations and "B" not in a.allocations


def test_zero_value_campaign_in_priority_mode(tmp_path):
    """A zero-priority campaign among positive ones gets only the a_min floor share
    (M11 semantics), which floors to 0 at this window — not the lion's share."""
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "priority_proportional",
                                     "a_max": 1.0})
    _active(cm, "zero", "P1", priority=0.0)
    _active(cm, "pos", "P1", priority=10.0)
    a = _alloc(db, "P1")
    assert a.allocations["pos"] > a.allocations["zero"]


# --- multiple portfolios independent ---------------------------------------

def test_multiple_portfolios_independent(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P_a", "A", budget_spec={"total": 10, "mode": "equal", "a_max": 1.0})
    cm.create_portfolio("P_b", "B", budget_spec={"total": 8, "mode": "equal", "a_max": 1.0})
    _active(cm, "a1", "P_a", priority=1.0)
    _active(cm, "a2", "P_a", priority=1.0)
    _active(cm, "b1", "P_b", priority=1.0)
    allocs = {a.portfolio_id: a for a in PortfolioPlanner(db_path=db).allocate_budget_all()}
    assert allocs["P_a"].allocations == {"a1": 5, "a2": 5}
    assert allocs["P_b"].allocations == {"b1": 8}


def test_paused_portfolio_allocates_nothing(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", budget_spec={"total": 20, "mode": "equal"})
    _active(cm, "c", "P1", priority=1.0)
    cm.pause_portfolio("P1")
    a = _alloc(db, "P1")
    assert a.allocations == {}


# --- determinism / replay / rebuild ----------------------------------------

def test_deterministic_within_db(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "priority_proportional",
                                     "a_max": 0.5})
    _active(cm, "x", "P1", priority=2.0)
    _active(cm, "y", "P1", priority=1.0)
    planner = PortfolioPlanner(db_path=db)
    assert planner.allocate_budget("P1").as_dict() == \
        planner.allocate_budget("P1").as_dict()


def test_replay_determinism_identical_output(tmp_path):
    def build(name):
        db = _db(tmp_path, name)
        cm = _cm(db)
        cm.create_portfolio("P1", "Alpha",
                            budget_spec={"total": 20, "mode": "priority_proportional",
                                         "a_max": 0.5})
        _active(cm, "x", "P1", priority=3.0)
        _active(cm, "y", "P1", priority=1.0)
        _active(cm, "z", "P1", priority=2.0, budget_experiments=2)
        return PortfolioPlanner(db_path=db).allocate_budget("P1").as_dict()
    assert build("r1.db") == build("r2.db")


def test_rebuild_equivalence(tmp_path):
    """Allocation is identical after the campaign/portfolio projection rows are
    dropped and rebuilt from the event log (pure function of stored state)."""
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "equal", "a_max": 1.0})
    _active(cm, "a", "P1", priority=1.0)
    _active(cm, "b", "P1", priority=1.0)
    before = PortfolioPlanner(db_path=db).allocate_budget("P1").as_dict()
    cm.rebuild_portfolio_from_events("P1")
    cm.rebuild_from_events("a")
    cm.rebuild_from_events("b")
    after = PortfolioPlanner(db_path=db).allocate_budget("P1").as_dict()
    assert before == after


def test_allocation_is_pure_no_mutation(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "equal", "a_max": 1.0})
    _active(cm, "a", "P1", priority=1.0, budget_experiments=7)
    before_state = cm.current_state("a")
    before_budget = campaign_get_budget(db, "a")
    PortfolioPlanner(db_path=db).allocate_budget("P1")
    assert cm.current_state("a") == before_state
    assert campaign_get_budget(db, "a") == before_budget   # budget_experiments untouched


def campaign_get_budget(db, cid):
    from agents.storage import campaign_store
    return campaign_store.get_campaign(cid, db_path=db)["budget_experiments"]


# --- legacy compatibility --------------------------------------------------

def test_legacy_campaign_priority_from_goal_spec(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "priority_proportional",
                                     "a_max": 1.0})
    _active(cm, "hi", "P1", goal_spec={"priority": 3})   # legacy priority location
    _active(cm, "lo", "P1", goal_spec={"priority": 1})
    a = _alloc(db, "P1")
    assert a.allocations == {"hi": 15, "lo": 5}
