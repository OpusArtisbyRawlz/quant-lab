"""
M11 PR-4 — HoldoutEngine tests (holdout validation projection).

Proves the engine is a pure, replay-deterministic, idempotent fold of the
immutable ``evidence_event`` log into the rebuildable ``holdout_evaluation``
projection; that it is separate from the Promotion Engine (which only *consumes*
its output); and that it never mutates evidence or the PR-2 development posterior
("no peeking").
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import (
    evidence_store, holdout_store, hypothesis_state_store, promotion_store,
)
from agents.research_intelligence import (
    EvidenceProjector, PromotionEngine, HoldoutEngine,
)


def _fresh_db(tmp_path, name="holdout.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db, hid, windows, market="IN", universe="NIFTY", T=2520):
    """windows: list of (experiment_id, year, sharpe)."""
    for eid, yr, s in windows:
        evidence_store.record_evidence(
            eid, hypothesis_id=hid, market=market, universe=universe,
            regime="all", bar_type="time",
            date_start=f"{yr}-01-01", date_end=f"{yr}-12-31",
            metrics={"net_sharpe": s, "T": T, "N": 252, "K": 1}, db_path=db,
        )


def _robust(db, hid="Hrobust"):
    _seed(db, hid, [(f"{hid}-{i}", 2000 + i, 1.4) for i in range(24)])


def _overfit(db, hid="Hoverfit"):
    _seed(db, hid, [(f"{hid}-{i}", 2000 + i, 2.0) for i in range(17)]
                 + [(f"{hid}-{i}", 2000 + i, 0.1) for i in range(17, 24)])


def _no_ts(row):
    row = dict(row)
    row.pop("last_rebuilt_at", None)
    return row


# --- basic projection -----------------------------------------------------

def test_rebuild_writes_holdout_evaluation(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H")
    row = HoldoutEngine(db_path=db).rebuild_hypothesis("H")
    assert row is not None
    r = holdout_store.get_holdout("H", db_path=db)
    assert r["is_n"] > 0 and r["oos_n"] > 0
    assert r["method"] == "holdout_v1"
    assert r["delta_max"] == 0.5


def test_robust_strategy_passes_holdout(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H")
    HoldoutEngine(db_path=db).rebuild_hypothesis("H")
    r = holdout_store.get_holdout("H", db_path=db)
    assert r["holdout_pass"] == 1


def test_constructed_overfit_fails_holdout(tmp_path):
    db = _fresh_db(tmp_path)
    _overfit(db, "H")
    HoldoutEngine(db_path=db).rebuild_hypothesis("H")
    r = holdout_store.get_holdout("H", db_path=db)
    assert r["holdout_pass"] == 0
    # Overfit signature: large IS→OOS decay trips retention and/or overlap.
    assert r["cond_retention"] == 0 or r["cond_overlap"] == 0
    assert r["haircut"] > 1.0


def test_hypothesis_without_oos_is_not_evaluable(tmp_path):
    db = _fresh_db(tmp_path)
    # A single window → cannot form a temporal holdout (no OOS side).
    _seed(db, "H", [("only", 2015, 1.2)])
    assert HoldoutEngine(db_path=db).rebuild_hypothesis("H") is None
    assert holdout_store.get_holdout("H", db_path=db) is None


# --- determinism ----------------------------------------------------------

def test_rebuild_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H")
    eng = HoldoutEngine(db_path=db)
    eng.rebuild_hypothesis("H")
    first = _no_ts(holdout_store.get_holdout("H", db_path=db))
    eng.rebuild_hypothesis("H")
    second = _no_ts(holdout_store.get_holdout("H", db_path=db))
    assert first == second
    assert len(holdout_store.list_holdouts(db_path=db)) == 1


def test_projection_is_replay_deterministic_across_insertion_order(tmp_path):
    def build(order, name):
        db = _fresh_db(tmp_path, name)
        payload = [(f"E{i}", 2000 + i, 1.4) for i in range(24)]
        for idx in order:
            eid, yr, s = payload[idx]
            _seed(db, "H", [(eid, yr, s)])
        HoldoutEngine(db_path=db).rebuild_hypothesis("H")
        return _no_ts(holdout_store.get_holdout("H", db_path=db))

    a = build(list(range(24)), "a.db")
    b = build(list(reversed(range(24))), "b.db")
    assert a == b


def test_deterministic_rebuild_from_empty_database(tmp_path):
    db = _fresh_db(tmp_path)
    assert HoldoutEngine(db_path=db).rebuild_all() == []
    _robust(db, "H")
    HoldoutEngine(db_path=db).rebuild_all()
    before = _no_ts(holdout_store.get_holdout("H", db_path=db))
    with get_connection(db) as conn:
        conn.execute("DELETE FROM holdout_evaluation")
        conn.commit()
    assert holdout_store.get_holdout("H", db_path=db) is None
    HoldoutEngine(db_path=db).rebuild_all()
    after = _no_ts(holdout_store.get_holdout("H", db_path=db))
    assert before == after


def test_rebuild_all_covers_every_evaluable_hypothesis(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H1")
    _overfit(db, "H2")
    _seed(db, "H3", [("solo", 2015, 1.0)])   # not evaluable (no OOS)
    rebuilt = set(HoldoutEngine(db_path=db).rebuild_all())
    assert rebuilt == {"H1", "H2"}


# --- append-only evidence + no peeking ------------------------------------

def test_evidence_events_are_never_mutated(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H")

    def _snapshot():
        with get_connection(db) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT * FROM evidence_event ORDER BY id").fetchall()]

    before = _snapshot()
    HoldoutEngine(db_path=db).rebuild_all()
    HoldoutEngine(db_path=db).rebuild_all()
    assert _snapshot() == before


def test_holdout_does_not_touch_development_posterior(tmp_path):
    # "No peeking": computing the OOS gate must not alter the PR-2 development
    # posterior (hypothesis_state).
    db = _fresh_db(tmp_path)
    _robust(db, "H")
    EvidenceProjector(db_path=db).rebuild_all()
    before = _no_ts(hypothesis_state_store.get_hypothesis_state("H", db_path=db))
    HoldoutEngine(db_path=db).rebuild_all()
    after = _no_ts(hypothesis_state_store.get_hypothesis_state("H", db_path=db))
    assert before == after


def test_holdout_does_not_touch_m9_signal_cache(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H")

    def _counts():
        with get_connection(db) as conn:
            return (
                conn.execute("SELECT COUNT(*) c FROM signal_context_performance").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM signal_context_observation").fetchone()["c"],
            )

    before = _counts()
    HoldoutEngine(db_path=db).rebuild_all()
    assert _counts() == before


# --- Promotion Engine consumes holdout, never computes it -----------------

def test_promotion_consumes_holdout_evidence(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H")
    EvidenceProjector(db_path=db).rebuild_all()
    HoldoutEngine(db_path=db).rebuild_all()          # holdout computed first
    PromotionEngine(db_path=db).rebuild_all()        # promotion consumes it

    reco = promotion_store.get_recommendation("H", db_path=db)
    prodc = [g for g in reco["gate_detail"] if g["stage"] == "Production Candidate"][0]
    # holdout is now available → it drops out of the "unavailable" list; only the
    # not-yet-implemented FDR (§7.2) input remains unavailable.
    assert not any("holdout" in u for u in prodc["unavailable"])
    assert any("bh_fdr" in u for u in prodc["unavailable"])


def test_promotion_without_holdout_marks_it_unavailable(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H")
    EvidenceProjector(db_path=db).rebuild_all()
    PromotionEngine(db_path=db).rebuild_all()        # no HoldoutEngine run
    reco = promotion_store.get_recommendation("H", db_path=db)
    prodc = [g for g in reco["gate_detail"] if g["stage"] == "Production Candidate"][0]
    assert any("holdout" in u for u in prodc["unavailable"])


def test_holdout_pass_alone_does_not_reach_production_candidate(tmp_path):
    # Even a passing holdout cannot reach ProdC while BH-FDR (§7.2) is unavailable.
    db = _fresh_db(tmp_path)
    _robust(db, "H")
    EvidenceProjector(db_path=db).rebuild_all()
    HoldoutEngine(db_path=db).rebuild_all()
    PromotionEngine(db_path=db).rebuild_all()
    reco = promotion_store.get_recommendation("H", db_path=db)
    assert reco["recommended_stage"] != "Production Candidate"


# --- versioning + schema --------------------------------------------------

def test_versioning_is_respected(tmp_path):
    db = _fresh_db(tmp_path)
    _robust(db, "H")
    HoldoutEngine(db_path=db).rebuild_hypothesis("H")
    assert holdout_store.get_holdout("H", db_path=db)["method"] == "holdout_v1"


def test_projection_table_exists_and_is_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='holdout_evaluation'"
        ).fetchone() is not None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE holdout_evaluation")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='holdout_evaluation'"
        ).fetchone() is not None
