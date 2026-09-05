"""
M11 PR-7 — BudgetEngine tests (evidence-budget projection) + quota consumption.

Proves the engine is a pure, replay-deterministic, idempotent population fold of
the posterior + retirement determination into the rebuildable ``budget_allocation``
projection; that it mutates no evidence and no upstream projection; and that the
existing ExplorationPlanner consumes ``b_h`` through its **existing** ``accept``
seam with **no agent modified**.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import evidence_store, budget_store, hypothesis_state_store
from agents.research_intelligence import (
    EvidenceProjector, RetirementEngine, BudgetEngine,
)
from agents.research_intelligence.budget import budget_admission


def _fresh_db(tmp_path, name="budget.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db, hid, n, sharpe, start_i=0, yr0=2005, T=2520):
    for i in range(start_i, start_i + n):
        yr = yr0 + (i - start_i)
        evidence_store.record_evidence(
            f"{hid}-{i}", hypothesis_id=hid, market="IN", universe="NIFTY",
            regime="all", bar_type="time",
            date_start=f"{yr}-01-01", date_end=f"{yr}-12-31",
            metrics={"net_sharpe": sharpe, "T": T, "N": 252, "K": 1}, db_path=db,
        )


def _population(db):
    _seed(db, "Hprom", 4, 0.5, start_i=0)        # uncertain-promising
    _seed(db, "Hsat", 30, 1.6, start_i=100)      # saturated (tight)
    _seed(db, "Hbad", 8, -1.5, start_i=200)      # refuted → retired
    _seed(db, "Hmid", 5, 0.4, start_i=300)


def _project(db, window=20):
    EvidenceProjector(db_path=db).rebuild_all()
    RetirementEngine(db_path=db).rebuild_all()
    return BudgetEngine(db_path=db).rebuild_all(window=window)


def _no_ts(row):
    row = dict(row)
    row.pop("last_rebuilt_at", None)
    return row


# --- basic projection -----------------------------------------------------

def test_rebuild_writes_budget_allocation(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    built = _project(db)
    assert set(built) == {"Hprom", "Hsat", "Hbad", "Hmid"}
    r = budget_store.get_budget("Hprom", db_path=db)
    assert r["method"] == "budget_v1"
    assert r["window"] == 20


def test_retired_hypothesis_gets_zero_budget(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    _project(db)
    r = budget_store.get_budget("Hbad", db_path=db)
    assert r["retired"] == 1
    assert r["a_frac"] == 0.0 and r["b_experiments"] == 0


def test_saturated_gets_less_than_promising(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    _project(db)
    prom = budget_store.get_budget("Hprom", db_path=db)
    sat = budget_store.get_budget("Hsat", db_path=db)
    assert prom["evoi"] > sat["evoi"]
    assert prom["b_experiments"] >= sat["b_experiments"]


def test_a_max_ceiling_never_exceeded_across_population(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    _project(db)
    for r in budget_store.list_budgets(db_path=db):
        assert r["a_frac"] <= 0.25 + 1e-9


def test_window_scales_budget(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    RetirementEngine(db_path=db).rebuild_all()
    BudgetEngine(db_path=db).rebuild_all(window=20)
    small = budget_store.get_budget("Hprom", db_path=db)["b_experiments"]
    BudgetEngine(db_path=db).rebuild_all(window=200)
    big = budget_store.get_budget("Hprom", db_path=db)["b_experiments"]
    assert big > small


# --- determinism ----------------------------------------------------------

def test_rebuild_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    _project(db)
    first = {r["hypothesis_id"]: _no_ts(r) for r in budget_store.list_budgets(db_path=db)}
    BudgetEngine(db_path=db).rebuild_all(window=20)
    second = {r["hypothesis_id"]: _no_ts(r) for r in budget_store.list_budgets(db_path=db)}
    assert first == second


def test_projection_is_replay_deterministic_across_insertion_order(tmp_path):
    def build(order, name):
        db = _fresh_db(tmp_path, name)
        seeds = [("Hprom", 4, 0.5, 0), ("Hsat", 30, 1.6, 100),
                 ("Hbad", 8, -1.5, 200), ("Hmid", 5, 0.4, 300)]
        for idx in order:
            hid, n, s, start = seeds[idx]
            _seed(db, hid, n, s, start_i=start)
        _project(db)
        return {r["hypothesis_id"]: _no_ts(r) for r in budget_store.list_budgets(db_path=db)}

    assert build([0, 1, 2, 3], "a.db") == build([3, 1, 0, 2], "b.db")


def test_deterministic_rebuild_from_empty_database(tmp_path):
    db = _fresh_db(tmp_path)
    assert BudgetEngine(db_path=db).rebuild_all() == []
    _population(db)
    _project(db)
    before = {r["hypothesis_id"]: _no_ts(r) for r in budget_store.list_budgets(db_path=db)}
    with get_connection(db) as conn:
        conn.execute("DELETE FROM budget_allocation")
        conn.commit()
    BudgetEngine(db_path=db).rebuild_all(window=20)
    after = {r["hypothesis_id"]: _no_ts(r) for r in budget_store.list_budgets(db_path=db)}
    assert before == after


def test_population_prune_removes_stale_rows(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    _project(db)
    assert budget_store.get_budget("Hmid", db_path=db) is not None
    with get_connection(db) as conn:
        conn.execute("DELETE FROM hypothesis_state WHERE hypothesis_id='Hmid'")
        conn.commit()
    BudgetEngine(db_path=db).rebuild_all(window=20)
    assert budget_store.get_budget("Hmid", db_path=db) is None


# --- append-only evidence + boundaries ------------------------------------

def test_evidence_events_are_never_mutated(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    RetirementEngine(db_path=db).rebuild_all()

    def _snapshot():
        with get_connection(db) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT * FROM evidence_event ORDER BY id").fetchall()]

    before = _snapshot()
    BudgetEngine(db_path=db).rebuild_all(window=20)
    BudgetEngine(db_path=db).rebuild_all(window=20)
    assert _snapshot() == before


def test_budget_does_not_touch_posterior_retirement_or_promotion(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    RetirementEngine(db_path=db).rebuild_all()
    before_state = {r["hypothesis_id"]: _no_ts(r)
                    for r in hypothesis_state_store.list_hypothesis_states(db_path=db)}

    def _counts():
        with get_connection(db) as conn:
            return (
                conn.execute("SELECT COUNT(*) c FROM signal_context_performance").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM promotion_recommendation").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM retirement_evaluation").fetchone()["c"],
            )

    before_counts = _counts()
    BudgetEngine(db_path=db).rebuild_all(window=20)
    after_state = {r["hypothesis_id"]: _no_ts(r)
                   for r in hypothesis_state_store.list_hypothesis_states(db_path=db)}
    assert after_state == before_state             # posterior untouched (consumed only)
    assert _counts() == before_counts              # writes neither M9, promotion, nor retirement


def test_versioning_is_respected(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    _project(db)
    assert budget_store.get_budget("Hprom", db_path=db)["method"] == "budget_v1"


# --- consumption via the EXISTING quota `accept` seam (no agent modified) --

def test_budget_consumed_through_existing_quota_accept_seam(tmp_path):
    from agents.research_quota.quota import (
        ExplorationPlanner, QuotaConfig, Candidate, BUCKET_EXPLORE,
    )
    db = _fresh_db(tmp_path)
    _population(db)
    _project(db, window=20)
    bmap = budget_store.budget_map(db_path=db)     # {hypothesis_id: b_h}

    # 10 candidates all belonging to Hprom; the quota's own accept seam enforces b_h.
    cands = [Candidate(idea_id=f"i{i}", bucket=BUCKET_EXPLORE,
                       context_key=("f", "IN", "NIFTY", "time"), order=i,
                       payload={"hid": "Hprom"}) for i in range(10)]
    accept = budget_admission(bmap, key_fn=lambda c: c.payload["hid"])
    planner = ExplorationPlanner(QuotaConfig(max_per_context=None))
    plan = planner.plan(cands, window=20, accept=accept)

    # Exactly Hprom's budget was admitted and the rest were dropped by the
    # admission gate — enforced purely through the pre-existing `accept` callback;
    # no quota code was changed.
    b = bmap["Hprom"]
    assert b >= 1                                   # Hprom did receive some budget
    assert len(plan.selected) == b
    assert len(plan.dropped_for_admission) == 10 - b


# --- schema ---------------------------------------------------------------

def test_projection_table_exists_and_is_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='budget_allocation'"
        ).fetchone() is not None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE budget_allocation")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='budget_allocation'"
        ).fetchone() is not None
