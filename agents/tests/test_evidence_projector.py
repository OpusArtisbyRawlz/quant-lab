"""
M11 PR-2 — EvidenceProjector tests (posterior projection over the evidence log).

Proves the projector is a pure, replay-deterministic, idempotent fold of the
immutable ``evidence_event`` log into the ``hypothesis_state`` /
``context_cell_posterior`` projections, that it keeps holdout evidence out of the
development posterior, leaves M9 tables untouched, and writes **no** lifecycle
decision (stage stays 'Candidate').
"""

from __future__ import annotations

import json

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import evidence_store, hypothesis_state_store
from agents.research_intelligence import EvidenceProjector


def _fresh_db(tmp_path, name="proj.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db, hypothesis_id="H1", n=8, sharpe=1.0, source=evidence_store.SOURCE_IN_SAMPLE,
          market="IN", universe="NIFTY", regime="all", bar_type="time",
          start_i=0):
    for i in range(start_i, start_i + n):
        evidence_store.record_evidence(
            f"EXP-{i}", evidence_source=source, hypothesis_id=hypothesis_id,
            market=market, universe=universe, regime=regime, bar_type=bar_type,
            date_start="2020-01-01", date_end="2024-12-31",
            metrics={"net_sharpe": sharpe, "T": 252, "N": 252, "K": 1},
            db_path=db,
        )


# --- basic projection -----------------------------------------------------

def test_rebuild_writes_hypothesis_state(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", n=10, sharpe=1.0)
    row = EvidenceProjector(db_path=db).rebuild_hypothesis("H1")

    assert row is not None
    st = hypothesis_state_store.get_hypothesis_state("H1", db_path=db)
    assert st["posterior_mean"] > 0.5
    assert st["ci_low"] < st["posterior_mean"] < st["ci_high"]
    assert 0.0 <= st["q_stat_prob"] <= 1.0
    assert st["q_stat_prob"] > 0.99
    assert st["n_supporting"] == 10
    assert st["method"] == "stat_v1"


def test_rebuild_writes_cell_posteriors(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", n=4, market="IN", regime="low_vol")
    _seed(db, "H1", n=4, market="US", regime="high_vol", start_i=100)
    EvidenceProjector(db_path=db).rebuild_hypothesis("H1")

    cells = hypothesis_state_store.list_cell_posteriors("H1", db_path=db)
    assert len(cells) == 2
    for c in cells:
        assert c["post_ci_low"] < c["post_mu"] < c["post_ci_high"]
        assert c["m"] == 4


# --- decision-free --------------------------------------------------------

def test_projection_stage_is_candidate_no_decision(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", n=30, sharpe=3.0)      # overwhelming evidence
    EvidenceProjector(db_path=db).rebuild_hypothesis("H1")
    st = hypothesis_state_store.get_hypothesis_state("H1", db_path=db)
    # Even with strong evidence, PR-2 makes no promotion: stage stays Candidate.
    assert st["stage"] == "Candidate"


# --- idempotent + replay-deterministic ------------------------------------

def _state_no_ts(db, hid="H1"):
    st = hypothesis_state_store.get_hypothesis_state(hid, db_path=db)
    st.pop("last_rebuilt_at")
    return st


def test_rebuild_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", n=8)
    proj = EvidenceProjector(db_path=db)
    proj.rebuild_hypothesis("H1")
    first = _state_no_ts(db)
    proj.rebuild_hypothesis("H1")
    second = _state_no_ts(db)
    assert first == second
    # No duplicate cell rows on re-fold.
    assert len(hypothesis_state_store.list_cell_posteriors("H1", db_path=db)) == 1


def test_projection_is_replay_deterministic_across_insertion_order(tmp_path):
    # Two DBs seeded with the SAME evidence in DIFFERENT insertion orders must
    # produce byte-identical projections (Δ clock is run-time, not insertion).
    def build(order, name):
        db = _fresh_db(tmp_path, name)
        payload = [
            ("EXP-a", "2021-06-30", 1.2), ("EXP-b", "2022-06-30", 0.8),
            ("EXP-c", "2023-06-30", 1.5), ("EXP-d", "2024-06-30", 0.4),
        ]
        for idx in order:
            eid, dend, s = payload[idx]
            evidence_store.record_evidence(
                eid, hypothesis_id="H1", market="IN", universe="NIFTY",
                regime="all", bar_type="time",
                date_start="2020-01-01", date_end=dend,
                metrics={"net_sharpe": s, "T": 252, "N": 252, "K": 1},
                db_path=db,
            )
        EvidenceProjector(db_path=db).rebuild_hypothesis("H1")
        return _state_no_ts(db)

    a = build([0, 1, 2, 3], "a.db")
    b = build([3, 1, 0, 2], "b.db")
    assert a == b


# --- holdout kept out of development posterior ----------------------------

def test_holdout_evidence_excluded_from_development_posterior(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", n=6, sharpe=1.0, source=evidence_store.SOURCE_IN_SAMPLE)
    # A holdout row with a wildly different value must not move the dev posterior.
    evidence_store.record_evidence(
        "EXP-OOS", evidence_source=evidence_store.SOURCE_HOLDOUT,
        hypothesis_id="H1", market="IN", universe="NIFTY", regime="all",
        bar_type="time", metrics={"net_sharpe": -9.0, "T": 252, "N": 252},
        db_path=db,
    )
    EvidenceProjector(db_path=db).rebuild_hypothesis("H1")
    st = hypothesis_state_store.get_hypothesis_state("H1", db_path=db)
    assert st["posterior_mean"] > 0.5          # unaffected by the holdout row
    assert st["n_supporting"] == 6


# --- rebuild_all ----------------------------------------------------------

def test_rebuild_all_covers_every_hypothesis(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", n=4, start_i=0)
    _seed(db, "H2", n=4, start_i=100)
    rebuilt = EvidenceProjector(db_path=db).rebuild_all()
    assert set(rebuilt) == {"H1", "H2"}
    assert hypothesis_state_store.get_hypothesis_state("H1", db_path=db) is not None
    assert hypothesis_state_store.get_hypothesis_state("H2", db_path=db) is not None


def test_hypothesis_without_usable_evidence_is_skipped(tmp_path):
    db = _fresh_db(tmp_path)
    # Evidence with no net_sharpe/sharpe metric → nothing to fold.
    evidence_store.record_evidence(
        "EXP-x", hypothesis_id="H1", metrics={"auc": 0.5}, db_path=db
    )
    assert EvidenceProjector(db_path=db).rebuild_hypothesis("H1") is None
    assert hypothesis_state_store.get_hypothesis_state("H1", db_path=db) is None


# --- M9 boundary preserved ------------------------------------------------

def test_projection_does_not_touch_m9_signal_cache(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", n=6)

    def _counts():
        with get_connection(db) as conn:
            return (
                conn.execute("SELECT COUNT(*) c FROM signal_context_performance").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM signal_context_observation").fetchone()["c"],
            )

    before = _counts()
    EvidenceProjector(db_path=db).rebuild_all()
    assert _counts() == before


# --- schema ---------------------------------------------------------------

def test_projection_tables_exist_and_are_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        for t in ("hypothesis_state", "context_cell_posterior"):
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone() is not None
    # Dropping a projection and re-creating it is safe (droppable cache).
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE hypothesis_state")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hypothesis_state'"
        ).fetchone() is not None
