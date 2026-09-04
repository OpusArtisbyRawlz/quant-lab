"""
M11 PR-5 — FdrEngine tests (population multiple-testing projection).

Proves the engine is a pure, replay-deterministic, idempotent, population-level
fold of the stat_v1 posterior (lfdr) + the immutable evidence log (frequentist
p-values) into the rebuildable ``fdr_evaluation`` projection; that it mutates no
evidence; and that the Promotion Engine consumes its output (Bayesian admission
gates Validated+, BH q gates Production Candidate) without computing it.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import evidence_store, fdr_store, promotion_store
from agents.research_intelligence import (
    EvidenceProjector, HoldoutEngine, FdrEngine, PromotionEngine,
)


def _fresh_db(tmp_path, name="fdr.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db, hid, n, sharpe, market="IN", regime="all", start_i=0, yr0=2005, T=2520):
    for i in range(start_i, start_i + n):
        yr = yr0 + (i - start_i)
        evidence_store.record_evidence(
            f"{hid}-{i}", hypothesis_id=hid, market=market, universe="NIFTY",
            regime=regime, bar_type="time",
            date_start=f"{yr}-01-01", date_end=f"{yr}-12-31",
            metrics={"net_sharpe": sharpe, "T": T, "N": 252, "K": 1}, db_path=db,
        )


def _population(db):
    """A strong, a mid, and a null hypothesis → non-trivial FDR population."""
    _seed(db, "Hstrong", 12, 1.6, start_i=0)
    _seed(db, "Hmid", 8, 0.9, start_i=100)
    _seed(db, "Hnull", 8, 0.0, start_i=200)


def _no_ts(row):
    row = dict(row)
    row.pop("last_rebuilt_at", None)
    return row


# --- basic projection -----------------------------------------------------

def test_rebuild_writes_fdr_evaluation(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    built = FdrEngine(db_path=db).rebuild_all()
    assert set(built) == {"Hstrong", "Hmid", "Hnull"}
    r = fdr_store.get_fdr("Hstrong", db_path=db)
    assert r["method"] == "fdr_v1"
    assert r["population_size"] == 3
    assert r["alpha"] == 0.10


def test_strong_hypothesis_admitted_null_rejected(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    FdrEngine(db_path=db).rebuild_all()
    strong = fdr_store.get_fdr("Hstrong", db_path=db)
    null = fdr_store.get_fdr("Hnull", db_path=db)
    # Bayesian FDR: strong (lfdr≈0) admitted; null (lfdr≈0.5) not.
    assert strong["bayes_admitted"] == 1
    assert null["bayes_admitted"] == 0
    # BH cross-check agrees in direction: strong q small, null q large.
    assert strong["q_value"] < 0.05
    assert null["q_value"] > 0.05
    assert null["p_value"] == pytest.approx(0.5, abs=1e-6)


# --- determinism ----------------------------------------------------------

def test_rebuild_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    eng = FdrEngine(db_path=db)
    eng.rebuild_all()
    first = {r["hypothesis_id"]: _no_ts(r) for r in fdr_store.list_fdr(db_path=db)}
    eng.rebuild_all()
    second = {r["hypothesis_id"]: _no_ts(r) for r in fdr_store.list_fdr(db_path=db)}
    assert first == second
    assert len(fdr_store.list_fdr(db_path=db)) == 3


def test_projection_is_replay_deterministic_across_insertion_order(tmp_path):
    def build(order, name):
        db = _fresh_db(tmp_path, name)
        seeds = [("Hstrong", 12, 1.6, 0), ("Hmid", 8, 0.9, 100), ("Hnull", 8, 0.0, 200)]
        for idx in order:
            hid, n, s, start = seeds[idx]
            _seed(db, hid, n, s, start_i=start)
        EvidenceProjector(db_path=db).rebuild_all()
        FdrEngine(db_path=db).rebuild_all()
        return {r["hypothesis_id"]: _no_ts(r) for r in fdr_store.list_fdr(db_path=db)}

    assert build([0, 1, 2], "a.db") == build([2, 0, 1], "b.db")


def test_deterministic_rebuild_from_empty_database(tmp_path):
    db = _fresh_db(tmp_path)
    assert FdrEngine(db_path=db).rebuild_all() == []
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    FdrEngine(db_path=db).rebuild_all()
    before = {r["hypothesis_id"]: _no_ts(r) for r in fdr_store.list_fdr(db_path=db)}
    with get_connection(db) as conn:
        conn.execute("DELETE FROM fdr_evaluation")
        conn.commit()
    FdrEngine(db_path=db).rebuild_all()
    after = {r["hypothesis_id"]: _no_ts(r) for r in fdr_store.list_fdr(db_path=db)}
    assert before == after


def test_population_prune_removes_stale_rows(tmp_path):
    # If a hypothesis leaves the population, its stale FDR row is pruned on rebuild.
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    FdrEngine(db_path=db).rebuild_all()
    assert fdr_store.get_fdr("Hnull", db_path=db) is not None
    with get_connection(db) as conn:      # drop Hnull's posterior from the population
        conn.execute("DELETE FROM hypothesis_state WHERE hypothesis_id='Hnull'")
        conn.commit()
    FdrEngine(db_path=db).rebuild_all()
    assert fdr_store.get_fdr("Hnull", db_path=db) is None


# --- append-only evidence -------------------------------------------------

def test_evidence_events_are_never_mutated(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()

    def _snapshot():
        with get_connection(db) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT * FROM evidence_event ORDER BY id").fetchall()]

    before = _snapshot()
    FdrEngine(db_path=db).rebuild_all()
    FdrEngine(db_path=db).rebuild_all()
    assert _snapshot() == before


def test_fdr_does_not_touch_posterior_or_m9(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()

    def _counts():
        with get_connection(db) as conn:
            return (
                conn.execute("SELECT COUNT(*) c FROM hypothesis_state").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM signal_context_performance").fetchone()["c"],
            )

    before = _counts()
    FdrEngine(db_path=db).rebuild_all()
    assert _counts() == before


# --- Promotion consumes FDR, never computes it ----------------------------

def test_validated_requires_fdr_admission(tmp_path):
    # Without the FdrEngine, the §7.1 admission input is unavailable → a strong,
    # multi-cell hypothesis cannot reach Validated.
    db = _fresh_db(tmp_path)
    _seed(db, "H", 10, 1.6, market="IN", regime="low_vol")
    _seed(db, "H", 10, 1.6, market="US", regime="high_vol", start_i=100)
    EvidenceProjector(db_path=db).rebuild_all()
    PromotionEngine(db_path=db).rebuild_all()      # no FdrEngine run
    reco = promotion_store.get_recommendation("H", db_path=db)
    validated = [g for g in reco["gate_detail"] if g["stage"] == "Validated"][0]
    assert any("bayes_fdr_admission" in u for u in validated["unavailable"])
    assert reco["recommended_stage"] == "Promising"


def test_fully_qualified_hypothesis_reaches_production_candidate(tmp_path):
    # With every engine run, a strong hypothesis across ≥3 cells with a passing
    # holdout and FDR admission + q≤0.05 reaches Production Candidate — the first
    # stage in the whole M11 build that becomes reachable.
    db = _fresh_db(tmp_path)
    for rg, start in (("low_vol", 0), ("high_vol", 100), ("trend", 200)):
        _seed(db, "Hstar", 12, 1.6, regime=rg, start_i=start)
    _seed(db, "Hnull", 8, 0.0, start_i=500)        # population for FDR
    EvidenceProjector(db_path=db).rebuild_all()
    HoldoutEngine(db_path=db).rebuild_all()
    FdrEngine(db_path=db).rebuild_all()
    PromotionEngine(db_path=db).rebuild_all()
    reco = promotion_store.get_recommendation("Hstar", db_path=db)
    assert reco["recommended_stage"] == "Production Candidate"
    prodc = [g for g in reco["gate_detail"] if g["stage"] == "Production Candidate"][0]
    assert prodc["passed"] is True
    assert prodc["failures"] == [] and prodc["unavailable"] == []


def test_versioning_is_respected(tmp_path):
    db = _fresh_db(tmp_path)
    _population(db)
    EvidenceProjector(db_path=db).rebuild_all()
    FdrEngine(db_path=db).rebuild_all()
    assert fdr_store.get_fdr("Hstrong", db_path=db)["method"] == "fdr_v1"


# --- schema ---------------------------------------------------------------

def test_projection_table_exists_and_is_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fdr_evaluation'"
        ).fetchone() is not None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE fdr_evaluation")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fdr_evaluation'"
        ).fetchone() is not None
