"""
M11 PR-6 — RetirementEngine tests (retirement-track projection).

Proves the engine is a pure, replay-deterministic, idempotent fold of the PR-2
posterior into the rebuildable ``retirement_evaluation`` projection; that it
mutates no evidence and no posterior; that it reopens automatically on new
evidence (§3.2); and that it stays separate from the Promotion Engine.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import evidence_store, retirement_store, hypothesis_state_store
from agents.research_intelligence import EvidenceProjector, RetirementEngine
from agents.research_intelligence.retirement import LIVE, RETIRED_REFUTED


def _fresh_db(tmp_path, name="ret.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db, hid, n, sharpe, start_i=0, yr0=2010, T=2520):
    for i in range(start_i, start_i + n):
        yr = yr0 + (i - start_i)
        evidence_store.record_evidence(
            f"{hid}-{i}", hypothesis_id=hid, market="IN", universe="NIFTY",
            regime="all", bar_type="time",
            date_start=f"{yr}-01-01", date_end=f"{yr}-12-31",
            metrics={"net_sharpe": sharpe, "T": T, "N": 252, "K": 1}, db_path=db,
        )


def _project_and_retire(db):
    EvidenceProjector(db_path=db).rebuild_all()
    return RetirementEngine(db_path=db).rebuild_all()


def _no_ts(row):
    row = dict(row)
    row.pop("last_rebuilt_at", None)
    return row


# --- basic projection -----------------------------------------------------

def test_rebuild_writes_retirement_evaluation(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", 8, 1.4)
    built = _project_and_retire(db)
    assert built == ["H"]
    r = retirement_store.get_retirement("H", db_path=db)
    assert r["method"] == "retirement_v1"
    assert r["state"] == LIVE


def test_refuted_hypothesis_is_retired(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hbad", 8, -1.5)     # strongly negative → posterior below break-even
    _project_and_retire(db)
    r = retirement_store.get_retirement("Hbad", db_path=db)
    assert r["state"] == RETIRED_REFUTED
    assert r["retired"] == 1 and r["refuted"] == 1
    assert r["ci_high"] < 0.5


def test_strong_and_weak_positive_stay_live(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hstrong", 8, 1.4, start_i=0)
    _seed(db, "Hweak", 6, 0.1, start_i=100)     # weak but π > ε_ref → not refuted
    _project_and_retire(db)
    assert retirement_store.get_retirement("Hstrong", db_path=db)["state"] == LIVE
    assert retirement_store.get_retirement("Hweak", db_path=db)["state"] == LIVE


def test_hypothesis_without_posterior_gets_no_row(tmp_path):
    db = _fresh_db(tmp_path)
    evidence_store.record_evidence("EXP-x", hypothesis_id="H", metrics={"auc": 0.5}, db_path=db)
    EvidenceProjector(db_path=db).rebuild_all()
    assert RetirementEngine(db_path=db).rebuild_hypothesis("H") is None
    assert retirement_store.get_retirement("H", db_path=db) is None


# --- reopen on new evidence (§3.2) ----------------------------------------

def test_reopens_when_new_evidence_lifts_posterior(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", 8, -1.5)                      # refuted first
    _project_and_retire(db)
    assert retirement_store.get_retirement("H", db_path=db)["state"] == RETIRED_REFUTED
    # New, strong positive evidence arrives (append-only) → posterior flips.
    _seed(db, "H", 30, 2.0, start_i=100, yr0=2019)
    _project_and_retire(db)
    assert retirement_store.get_retirement("H", db_path=db)["state"] == LIVE


# --- determinism ----------------------------------------------------------

def test_rebuild_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", 8, -1.5)
    _project_and_retire(db)
    first = _no_ts(retirement_store.get_retirement("H", db_path=db))
    RetirementEngine(db_path=db).rebuild_all()
    second = _no_ts(retirement_store.get_retirement("H", db_path=db))
    assert first == second
    assert len(retirement_store.list_retirements(db_path=db)) == 1


def test_projection_is_replay_deterministic_across_insertion_order(tmp_path):
    def build(order, name):
        db = _fresh_db(tmp_path, name)
        payload = [("Hbad", 8, -1.5, 0), ("Hgood", 8, 1.4, 100), ("Hweak", 6, 0.1, 200)]
        for idx in order:
            hid, n, s, start = payload[idx]
            _seed(db, hid, n, s, start_i=start)
        _project_and_retire(db)
        return {r["hypothesis_id"]: _no_ts(r)
                for r in retirement_store.list_retirements(db_path=db)}

    assert build([0, 1, 2], "a.db") == build([2, 0, 1], "b.db")


def test_deterministic_rebuild_from_empty_database(tmp_path):
    db = _fresh_db(tmp_path)
    assert RetirementEngine(db_path=db).rebuild_all() == []
    _seed(db, "H", 8, -1.5)
    _project_and_retire(db)
    before = _no_ts(retirement_store.get_retirement("H", db_path=db))
    with get_connection(db) as conn:
        conn.execute("DELETE FROM retirement_evaluation")
        conn.commit()
    RetirementEngine(db_path=db).rebuild_all()
    after = _no_ts(retirement_store.get_retirement("H", db_path=db))
    assert before == after


def test_population_prune_removes_stale_rows(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H1", 8, 1.4, start_i=0)
    _seed(db, "H2", 8, -1.5, start_i=100)
    _project_and_retire(db)
    assert retirement_store.get_retirement("H2", db_path=db) is not None
    with get_connection(db) as conn:
        conn.execute("DELETE FROM hypothesis_state WHERE hypothesis_id='H2'")
        conn.commit()
    RetirementEngine(db_path=db).rebuild_all()
    assert retirement_store.get_retirement("H2", db_path=db) is None


# --- append-only evidence + boundaries ------------------------------------

def test_evidence_events_are_never_mutated(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", 8, -1.5)

    def _snapshot():
        with get_connection(db) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT * FROM evidence_event ORDER BY id").fetchall()]

    EvidenceProjector(db_path=db).rebuild_all()
    before = _snapshot()
    RetirementEngine(db_path=db).rebuild_all()
    RetirementEngine(db_path=db).rebuild_all()
    assert _snapshot() == before


def test_retirement_does_not_touch_posterior(tmp_path):
    # Consume, don't recompute: the PR-2 posterior projection is untouched.
    db = _fresh_db(tmp_path)
    _seed(db, "H", 8, -1.5)
    EvidenceProjector(db_path=db).rebuild_all()
    before = _no_ts(hypothesis_state_store.get_hypothesis_state("H", db_path=db))
    RetirementEngine(db_path=db).rebuild_all()
    after = _no_ts(hypothesis_state_store.get_hypothesis_state("H", db_path=db))
    assert before == after


def test_retirement_does_not_touch_m9_or_promotion(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", 8, -1.5)
    EvidenceProjector(db_path=db).rebuild_all()

    def _counts():
        with get_connection(db) as conn:
            return (
                conn.execute("SELECT COUNT(*) c FROM signal_context_performance").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM promotion_recommendation").fetchone()["c"],
            )

    before = _counts()
    RetirementEngine(db_path=db).rebuild_all()
    assert _counts() == before      # separate track: writes neither M9 nor promotion


def test_versioning_is_respected(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", 8, 1.4)
    _project_and_retire(db)
    assert retirement_store.get_retirement("H", db_path=db)["method"] == "retirement_v1"


# --- schema ---------------------------------------------------------------

def test_projection_table_exists_and_is_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='retirement_evaluation'"
        ).fetchone() is not None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE retirement_evaluation")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='retirement_evaluation'"
        ).fetchone() is not None
