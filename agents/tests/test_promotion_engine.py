"""
M11 PR-3 — PromotionEngine tests (lifecycle recommendation projection).

Proves the engine is a pure, replay-deterministic, idempotent fold of PR-2's
``hypothesis_state`` posterior projection (plus PR-1 provenance) into the
rebuildable ``promotion_recommendation`` projection — recomputing no statistics,
mutating no evidence, and making no auto-promotion.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import evidence_store, promotion_store, hypothesis_state_store
from agents.research_intelligence import EvidenceProjector, PromotionEngine
from agents.research_intelligence.promotion import (
    CANDIDATE, PROMISING, VALIDATED, PRODUCTION_CANDIDATE,
)
from agents.experiment_runner.robustness import FLAG_SUBPERIOD


def _fresh_db(tmp_path, name="promo.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db, hypothesis_id="H1", n=8, sharpe=1.0,
          source=evidence_store.SOURCE_IN_SAMPLE, market="IN", universe="NIFTY",
          regime="all", bar_type="time", start_i=0, robustness_flags=None):
    for i in range(start_i, start_i + n):
        evidence_store.record_evidence(
            f"EXP-{i}", evidence_source=source, hypothesis_id=hypothesis_id,
            market=market, universe=universe, regime=regime, bar_type=bar_type,
            date_start="2020-01-01", date_end="2024-12-31",
            metrics={"net_sharpe": sharpe, "T": 252, "N": 252, "K": 1},
            robustness_flags=robustness_flags,
            db_path=db,
        )


def _project_and_promote(db, policy=None):
    EvidenceProjector(db_path=db).rebuild_all()
    eng = PromotionEngine(db_path=db) if policy is None else PromotionEngine(db_path=db, policy=policy)
    return eng.rebuild_all()


def _no_ts(row):
    row = dict(row)
    row.pop("last_rebuilt_at", None)
    return row


# --- basic projection -----------------------------------------------------

def test_single_weak_experiment_stays_candidate(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hweak", n=1, sharpe=1.0)
    _project_and_promote(db)
    r = promotion_store.get_recommendation("Hweak", db_path=db)
    assert r["recommended_stage"] == CANDIDATE
    assert r["promotion_tier"] == 0
    assert r["replica_count"] == 1
    assert r["method"] == "promotion_v1"


def test_multiple_independent_positive_experiments_increase_confidence(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hfew", n=3, sharpe=1.2)
    _seed(db, "Hmany", n=20, sharpe=1.2, start_i=100)
    _project_and_promote(db)
    few = promotion_store.get_recommendation("Hfew", db_path=db)
    many = promotion_store.get_recommendation("Hmany", db_path=db)
    # More independent supporting evidence ⇒ higher confidence (π) and a
    # non-decreasing ladder tier.
    assert many["confidence_score"] >= few["confidence_score"]
    assert many["promotion_tier"] >= few["promotion_tier"]


def test_contradictory_evidence_lowers_confidence(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hagree", n=8, sharpe=1.0)
    _seed(db, "Hconflict", n=4, sharpe=1.0, start_i=100)
    _seed(db, "Hconflict", n=4, sharpe=-1.0, start_i=200)
    _project_and_promote(db)
    agree = promotion_store.get_recommendation("Hagree", db_path=db)
    conflict = promotion_store.get_recommendation("Hconflict", db_path=db)
    assert conflict["confidence_score"] < agree["confidence_score"]
    assert conflict["r_sign"] < agree["r_sign"]
    assert conflict["promotion_tier"] <= agree["promotion_tier"]


def test_uncertainty_shrinks_as_evidence_accumulates(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hfew", n=3, sharpe=1.0)
    _seed(db, "Hmany", n=40, sharpe=1.0, start_i=100)
    _project_and_promote(db)
    few = promotion_store.get_recommendation("Hfew", db_path=db)
    many = promotion_store.get_recommendation("Hmany", db_path=db)
    assert many["posterior_sd"] < few["posterior_sd"]


# --- cap at Validated + decision-free -------------------------------------

def test_strong_hypothesis_capped_at_validated(tmp_path):
    db = _fresh_db(tmp_path)
    # Overwhelming, reproducible, multi-cell positive evidence.
    _seed(db, "H", n=10, sharpe=1.6, market="IN", regime="low_vol")
    _seed(db, "H", n=10, sharpe=1.6, market="US", regime="high_vol", start_i=100)
    _project_and_promote(db)
    r = promotion_store.get_recommendation("H", db_path=db)
    assert r["recommended_stage"] == VALIDATED   # never Production Candidate in PR-3
    prodc = [g for g in r["gate_detail"] if g["stage"] == PRODUCTION_CANDIDATE][0]
    assert prodc["passed"] is False
    assert any("not implemented" in u for u in prodc["unavailable"])


def test_unresolved_critical_robustness_flag_caps_below_validated(tmp_path):
    db = _fresh_db(tmp_path)
    # Strong two-cell evidence, but one experiment carries a critical flag.
    _seed(db, "H", n=8, sharpe=1.6, market="IN", regime="low_vol")
    _seed(db, "H", n=8, sharpe=1.6, market="US", regime="high_vol", start_i=100)
    _seed(db, "H", n=1, sharpe=1.6, market="US", regime="high_vol", start_i=999,
          robustness_flags=[FLAG_SUBPERIOD])
    _project_and_promote(db)
    r = promotion_store.get_recommendation("H", db_path=db)
    assert r["has_critical_flag"] == 1
    assert r["recommended_stage"] == PROMISING   # Validated blocked by the flag
    validated = [g for g in r["gate_detail"] if g["stage"] == VALIDATED][0]
    assert "unresolved_critical_robustness_flag" in validated["failures"]


# --- idempotent + replay-deterministic ------------------------------------

def test_rebuild_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", n=8)
    _project_and_promote(db)
    first = _no_ts(promotion_store.get_recommendation("H", db_path=db))
    PromotionEngine(db_path=db).rebuild_all()
    second = _no_ts(promotion_store.get_recommendation("H", db_path=db))
    assert first == second
    # One row per hypothesis — no duplicate accumulation.
    assert len(promotion_store.list_recommendations(db_path=db)) == 1


def test_projection_is_replay_deterministic_across_insertion_order(tmp_path):
    def build(order, name):
        db = _fresh_db(tmp_path, name)
        payload = [
            ("EXP-a", "2021-06-30", 1.2, "low_vol"),
            ("EXP-b", "2022-06-30", 0.8, "low_vol"),
            ("EXP-c", "2023-06-30", 1.5, "high_vol"),
            ("EXP-d", "2024-06-30", 1.1, "high_vol"),
        ]
        for idx in order:
            eid, dend, s, rg = payload[idx]
            evidence_store.record_evidence(
                eid, hypothesis_id="H", market="IN", universe="NIFTY",
                regime=rg, bar_type="time", date_start="2020-01-01", date_end=dend,
                metrics={"net_sharpe": s, "T": 252, "N": 252, "K": 1}, db_path=db,
            )
        _project_and_promote(db)
        return _no_ts(promotion_store.get_recommendation("H", db_path=db))

    a = build([0, 1, 2, 3], "a.db")
    b = build([3, 1, 0, 2], "b.db")
    assert a == b


# --- rebuild_all + empty-DB determinism -----------------------------------

def test_rebuild_all_covers_every_hypothesis_with_a_posterior(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", n=4, start_i=0)
    _seed(db, "H2", n=4, start_i=100)
    rebuilt = _project_and_promote(db)
    assert set(rebuilt) == {"H1", "H2"}


def test_hypothesis_without_posterior_gets_no_recommendation(tmp_path):
    db = _fresh_db(tmp_path)
    # Evidence with no usable performance metric → no hypothesis_state posterior.
    evidence_store.record_evidence("EXP-x", hypothesis_id="H", metrics={"auc": 0.5}, db_path=db)
    EvidenceProjector(db_path=db).rebuild_all()
    assert PromotionEngine(db_path=db).rebuild_hypothesis("H") is None
    assert promotion_store.get_recommendation("H", db_path=db) is None


def test_deterministic_rebuild_from_empty_database(tmp_path):
    db = _fresh_db(tmp_path)
    # Empty DB: nothing to recommend.
    assert PromotionEngine(db_path=db).rebuild_all() == []
    # Seed, project, promote.
    _seed(db, "H", n=8, sharpe=1.2)
    _project_and_promote(db)
    before = _no_ts(promotion_store.get_recommendation("H", db_path=db))
    # Drop the projection cache and rebuild from the immutable log → identical.
    with get_connection(db) as conn:
        conn.execute("DELETE FROM promotion_recommendation")
        conn.commit()
    assert promotion_store.get_recommendation("H", db_path=db) is None
    EvidenceProjector(db_path=db).rebuild_all()
    PromotionEngine(db_path=db).rebuild_all()
    after = _no_ts(promotion_store.get_recommendation("H", db_path=db))
    assert before == after


# --- append-only evidence is never mutated --------------------------------

def test_evidence_events_are_never_mutated(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", n=6)

    def _snapshot():
        with get_connection(db) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT * FROM evidence_event ORDER BY id").fetchall()]

    before = _snapshot()
    _project_and_promote(db)
    PromotionEngine(db_path=db).rebuild_all()   # a second fold, too
    assert _snapshot() == before


def test_recommendation_does_not_touch_hypothesis_state(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", n=6)
    EvidenceProjector(db_path=db).rebuild_all()
    before = _no_ts(hypothesis_state_store.get_hypothesis_state("H", db_path=db))
    PromotionEngine(db_path=db).rebuild_all()
    after = _no_ts(hypothesis_state_store.get_hypothesis_state("H", db_path=db))
    # Promotion is recommendation-only: PR-2's authoritative projection (incl. its
    # 'Candidate' stage) is left exactly as the posterior fold wrote it.
    assert before == after
    assert after["stage"] == "Candidate"


# --- versioning -----------------------------------------------------------

def test_versioning_is_respected(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", n=8)
    _project_and_promote(db)
    reco = promotion_store.get_recommendation("H", db_path=db)
    state = hypothesis_state_store.get_hypothesis_state("H", db_path=db)
    assert reco["method"] == "promotion_v1"
    assert state["method"] == "stat_v1"


# --- schema ---------------------------------------------------------------

def test_projection_table_exists_and_is_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='promotion_recommendation'"
        ).fetchone() is not None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE promotion_recommendation")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='promotion_recommendation'"
        ).fetchone() is not None
