"""
Phase 6 P6-12 — dependency-aware portfolio planning + cycle rejection.

Proves the PortfolioPlanner builds a deterministic, dependency-aware execution order
over the eligible set and rejects dependency cycles (§4: the graph is a DAG; cyclic
campaigns are excluded from the plan, never force-ordered). Eligibility/dependency
*satisfaction* stays owned by the CampaignManager (P6-11) — the planner only orders
and detects cycles. Pure: no execution, mutation, budget, or experiment evaluation.
"""

from __future__ import annotations

from agents.storage.db import create_all_tables
from agents.campaign_manager import CampaignManager, TRIGGER_DEPENDENCY
from agents.portfolio_planner import PortfolioPlanner, PortfolioPlan


def _db(tmp_path, name="dap.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _cm(db):
    return CampaignManager(db_path=db)


def _active(cm, cid, portfolio_id=None, *, activate=True, **fields):
    cm.create_campaign(cid, theme="t", portfolio_id=portfolio_id, **fields)
    if activate:
        cm.activate(cid)


def _on_active(dep_id):
    """A dependency edge satisfied while the prerequisite is co-runnable (ACTIVE),
    so both stay eligible and ordering (not filtering) is what's exercised."""
    return {"campaign_id": dep_id, "required_state": "ACTIVE"}


def _plan(db, pid):
    return PortfolioPlanner(db_path=db).plan(pid)


# --- linear dependency chains ----------------------------------------------

def test_linear_chain_ordered_prerequisite_first(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    # C depends on B depends on A, all co-runnable (required_state ACTIVE);
    # priorities are inverted so only dependency ordering could produce A,B,C.
    _active(cm, "A", "P1", priority=1.0)
    _active(cm, "B", "P1", priority=2.0, depends_on=[_on_active("A")])
    _active(cm, "C", "P1", priority=3.0, depends_on=[_on_active("B")])
    plan = _plan(db, "P1")
    assert plan.admitted == ["A", "B", "C"]
    assert plan.excluded_cycles == []


# --- branching dependency graphs -------------------------------------------

def test_branching_graph_respects_all_edges(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    # root → {b1, b2}; join depends on both b1 and b2.
    _active(cm, "root", "P1", priority=1.0)
    _active(cm, "b1", "P1", priority=5.0, depends_on=[_on_active("root")])
    _active(cm, "b2", "P1", priority=4.0, depends_on=[_on_active("root")])
    _active(cm, "join", "P1", priority=9.0,
            depends_on=[_on_active("b1"), _on_active("b2")])
    admitted = _plan(db, "P1").admitted
    # root before its children; both branches before join.
    assert admitted.index("root") < admitted.index("b1")
    assert admitted.index("root") < admitted.index("b2")
    assert admitted.index("b1") < admitted.index("join")
    assert admitted.index("b2") < admitted.index("join")
    # Ties (b1 vs b2, both root-dependent) break by policy (priority): b1(5) before b2(4).
    assert admitted == ["root", "b1", "b2", "join"]


# --- independent campaigns keep policy order -------------------------------

def test_independent_campaigns_pure_policy_order(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "lo", "P1", priority=1.0)
    _active(cm, "hi", "P1", priority=5.0)
    _active(cm, "mid", "P1", priority=3.0)
    assert _plan(db, "P1").admitted == ["hi", "mid", "lo"]


# --- dependency cycle handling (§4: reject) --------------------------------

def test_two_node_cycle_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "A", "P1", priority=1.0, depends_on=[_on_active("B")])
    _active(cm, "B", "P1", priority=2.0, depends_on=[_on_active("A")])
    _active(cm, "C", "P1", priority=9.0)                 # independent
    plan = _plan(db, "P1")
    assert plan.admitted == ["C"]
    assert plan.excluded_cycles == ["A", "B"]


def test_three_node_cycle_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "A", "P1", priority=1.0, depends_on=[_on_active("C")])
    _active(cm, "B", "P1", priority=2.0, depends_on=[_on_active("A")])
    _active(cm, "C", "P1", priority=3.0, depends_on=[_on_active("B")])
    _active(cm, "solo", "P1", priority=9.0)
    plan = _plan(db, "P1")
    assert plan.admitted == ["solo"]
    assert plan.excluded_cycles == ["A", "B", "C"]


def test_campaign_depending_on_cycle_also_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "A", "P1", priority=1.0, depends_on=[_on_active("B")])
    _active(cm, "B", "P1", priority=2.0, depends_on=[_on_active("A")])
    _active(cm, "D", "P1", priority=9.0, depends_on=[_on_active("A")])   # depends on the cycle
    plan = _plan(db, "P1")
    assert plan.admitted == []
    assert plan.excluded_cycles == ["A", "B", "D"]


def test_detect_cycles_api(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "A", "P1", depends_on=[_on_active("B")])
    _active(cm, "B", "P1", depends_on=[_on_active("A")])
    _active(cm, "C", "P1")
    assert PortfolioPlanner(db_path=db).detect_cycles("P1") == ["A", "B"]


def test_detect_cycles_empty_for_dag(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "A", "P1")
    _active(cm, "B", "P1", depends_on=[_on_active("A")])
    assert PortfolioPlanner(db_path=db).detect_cycles("P1") == []


def test_detect_cycles_ignores_external_dependency(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    cm.create_portfolio("P2", "Beta")
    _active(cm, "ext", "P2")
    _active(cm, "m", "P1", depends_on=[_on_active("ext")])   # dep outside P1
    # An external prerequisite is not part of P1's graph ⇒ no cycle.
    assert PortfolioPlanner(db_path=db).detect_cycles("P1") == []


# --- multiple portfolios ---------------------------------------------------

def test_multiple_portfolios_independent_dependency_graphs(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P_a", "A")
    cm.create_portfolio("P_b", "B")
    _active(cm, "a_root", "P_a", priority=1.0)
    _active(cm, "a_leaf", "P_a", priority=9.0, depends_on=[_on_active("a_root")])
    _active(cm, "b1", "P_b", priority=5.0)
    _active(cm, "b2", "P_b", priority=2.0, depends_on=[_on_active("b1")])
    plans = {p.portfolio_id: p.admitted
             for p in PortfolioPlanner(db_path=db).plan_all()}
    assert plans == {"P_a": ["a_root", "a_leaf"], "P_b": ["b1", "b2"]}


# --- lifecycle: archived / paused ------------------------------------------

def test_archived_and_stalled_excluded_from_graph(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "root", "P1", priority=1.0)
    _active(cm, "leaf", "P1", priority=9.0, depends_on=[_on_active("root")])
    _active(cm, "shelved", "P1", priority=8.0)
    _active(cm, "stalled", "P1", priority=7.0)
    cm.archive("shelved")
    cm.mark_stalled("stalled")
    assert _plan(db, "P1").admitted == ["root", "leaf"]


def test_paused_portfolio_empty_plan(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "root", "P1", priority=1.0)
    _active(cm, "leaf", "P1", priority=9.0, depends_on=[_on_active("root")])
    cm.pause_portfolio("P1")
    assert _plan(db, "P1").admitted == []


# --- empty portfolio -------------------------------------------------------

def test_empty_portfolio(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    plan = _plan(db, "P1")
    assert isinstance(plan, PortfolioPlan)
    assert plan.admitted == []
    assert plan.excluded_cycles == []


# --- deterministic ordering / replay ---------------------------------------

def test_deterministic_ordering_within_a_db(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "root", "P1", priority=1.0)
    _active(cm, "x", "P1", priority=2.0, depends_on=[_on_active("root")])
    _active(cm, "y", "P1", priority=2.0, depends_on=[_on_active("root")])
    planner = PortfolioPlanner(db_path=db)
    assert planner.plan("P1").admitted == planner.plan("P1").admitted == \
        ["root", "x", "y"]                              # equal-priority tie → campaign_id


def test_replay_determinism_identical_output(tmp_path):
    def build(name):
        db = _db(tmp_path, name)
        cm = _cm(db)
        cm.create_portfolio("P1", "Alpha", concurrency_limit=3)
        _active(cm, "root", "P1", priority=1.0)
        _active(cm, "b1", "P1", priority=5.0, depends_on=[_on_active("root")])
        _active(cm, "b2", "P1", priority=4.0, depends_on=[_on_active("root")])
        _active(cm, "join", "P1", priority=9.0,
                depends_on=[_on_active("b1"), _on_active("b2")])
        plan = PortfolioPlanner(db_path=db).plan("P1")
        return plan.admitted, plan.excluded_cycles
    assert build("r1.db") == build("r2.db")


def test_planning_is_pure_no_state_change(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha")
    _active(cm, "root", "P1", priority=1.0)
    _active(cm, "leaf", "P1", priority=9.0, depends_on=[_on_active("root")])
    before = {c: cm.current_state(c) for c in ("root", "leaf")}
    planner = PortfolioPlanner(db_path=db)
    planner.plan("P1")
    planner.detect_cycles("P1")
    assert {c: cm.current_state(c) for c in ("root", "leaf")} == before


# --- concurrency limit applies after dependency ordering -------------------

def test_concurrency_limit_after_dependency_order(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha", concurrency_limit=2)
    _active(cm, "root", "P1", priority=1.0)
    _active(cm, "mid", "P1", priority=5.0, depends_on=[_on_active("root")])
    _active(cm, "leaf", "P1", priority=9.0, depends_on=[_on_active("mid")])
    # Dependency order root, mid, leaf; limit 2 admits the first two.
    assert _plan(db, "P1").admitted == ["root", "mid"]
