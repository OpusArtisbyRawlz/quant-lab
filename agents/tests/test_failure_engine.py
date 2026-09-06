"""
M11 PR-9 — FailureClassifier tests (failure-taxonomy projection).

Proves the classifier is a pure, replay-deterministic, idempotent fold of the
immutable ``evidence_event`` log into the rebuildable ``failure_reason``
projection; that it mutates no evidence and never touches ``lessons_learned``.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import evidence_store, failure_store
from agents.research_intelligence import FailureClassifier
from agents.research_intelligence.failure import (
    REASON_NO_EDGE, REASON_COST_FRAGILITY, REASON_REJECTED_OTHER,
)


def _fresh_db(tmp_path, name="fail.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _rec(db, eid, decision=None, ns=1.0, T=2520, flags=None, source=None):
    kw = {} if source is None else {"evidence_source": source}
    evidence_store.record_evidence(
        eid, hypothesis_id="H", market="IN", universe="NIFTY", regime="all",
        bar_type="time", date_start="2020-01-01", date_end="2024-12-31",
        metrics={"net_sharpe": ns, "T": T}, robustness_flags=flags,
        critic_decision=decision, db_path=db, **kw)


def _no_ts(row):
    row = dict(row)
    row.pop("created_at", None)
    return row


# --- basic projection -----------------------------------------------------

def test_classify_writes_failures_only(tmp_path):
    db = _fresh_db(tmp_path)
    _rec(db, "good", "keep", 1.4)
    _rec(db, "bad", "reject", -0.5)
    failures = FailureClassifier(db_path=db).classify_all()
    assert failures == ["bad"]
    assert failure_store.get_failure("good", db_path=db) is None
    r = failure_store.get_failure("bad", db_path=db)
    assert r["reason_code"] == REASON_NO_EDGE
    assert r["method"] == "failure_v1"


def test_reason_codes_end_to_end(tmp_path):
    db = _fresh_db(tmp_path)
    _rec(db, "cost", "reject", 1.2, flags=["cost_fragility"])
    _rec(db, "bare", "reject", 1.2)
    FailureClassifier(db_path=db).classify_all()
    assert failure_store.get_failure("cost", db_path=db)["reason_code"] == REASON_COST_FRAGILITY
    assert failure_store.get_failure("bare", db_path=db)["reason_code"] == REASON_REJECTED_OTHER


def test_aggregates_flags_across_evidence_rows(tmp_path):
    db = _fresh_db(tmp_path)
    # Same experiment, two evidence sources; flags are the union.
    _rec(db, "E", "reject", 1.2, flags=["subperiod_instability"], source=evidence_store.SOURCE_IN_SAMPLE)
    _rec(db, "E", "reject", 1.2, flags=["cost_fragility"], source=evidence_store.SOURCE_VALIDATION)
    FailureClassifier(db_path=db).classify_all()
    r = failure_store.get_failure("E", db_path=db)
    assert r["reason_code"] == REASON_COST_FRAGILITY          # cost wins the priority
    assert r["evidence"]["robustness_flags"] == ["cost_fragility", "subperiod_instability"]


# --- determinism ----------------------------------------------------------

def test_classify_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _rec(db, "bad", "reject", -0.5)
    eng = FailureClassifier(db_path=db)
    eng.classify_all()
    first = _no_ts(failure_store.get_failure("bad", db_path=db))
    eng.classify_all()
    second = _no_ts(failure_store.get_failure("bad", db_path=db))
    assert first == second
    assert len(failure_store.list_failures(db_path=db)) == 1


def test_replay_deterministic_across_insertion_order(tmp_path):
    def build(order, name):
        db = _fresh_db(tmp_path, name)
        payload = [("a", "reject", -0.5, 2520, None), ("b", "reject", 1.2, 60, None),
                   ("c", "reject", 1.2, 2520, ["cost_fragility"])]
        for i in order:
            eid, dec, ns, T, fl = payload[i]
            _rec(db, eid, dec, ns, T, fl)
        FailureClassifier(db_path=db).classify_all()
        return {r["experiment_id"]: _no_ts(r) for r in failure_store.list_failures(db_path=db)}

    assert build([0, 1, 2], "a.db") == build([2, 0, 1], "b.db")


def test_deterministic_rebuild_from_empty_database(tmp_path):
    db = _fresh_db(tmp_path)
    assert FailureClassifier(db_path=db).classify_all() == []
    _rec(db, "bad", "reject", -0.5)
    FailureClassifier(db_path=db).classify_all()
    before = _no_ts(failure_store.get_failure("bad", db_path=db))
    with get_connection(db) as conn:
        conn.execute("DELETE FROM failure_reason")
        conn.commit()
    FailureClassifier(db_path=db).classify_all()
    after = _no_ts(failure_store.get_failure("bad", db_path=db))
    assert before == after


# --- pruning --------------------------------------------------------------

def test_non_failure_row_is_pruned(tmp_path):
    db = _fresh_db(tmp_path)
    _rec(db, "good", "keep", 1.4)
    failure_store.upsert_failure("good", REASON_NO_EDGE, db_path=db)  # stale row
    FailureClassifier(db_path=db).classify_experiment("good")
    assert failure_store.get_failure("good", db_path=db) is None      # pruned


def test_stale_experiment_row_is_pruned(tmp_path):
    db = _fresh_db(tmp_path)
    _rec(db, "bad", "reject", -0.5)
    failure_store.upsert_failure("ghost", REASON_REJECTED_OTHER, db_path=db)  # not in evidence
    FailureClassifier(db_path=db).classify_all()
    assert failure_store.get_failure("ghost", db_path=db) is None
    assert failure_store.get_failure("bad", db_path=db) is not None


# --- boundaries -----------------------------------------------------------

def test_evidence_events_are_never_mutated(tmp_path):
    db = _fresh_db(tmp_path)
    _rec(db, "bad", "reject", -0.5)

    def _snapshot():
        with get_connection(db) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT * FROM evidence_event ORDER BY id").fetchall()]

    before = _snapshot()
    FailureClassifier(db_path=db).classify_all()
    FailureClassifier(db_path=db).classify_all()
    assert _snapshot() == before


def test_does_not_touch_lessons_learned(tmp_path):
    db = _fresh_db(tmp_path)
    _rec(db, "bad", "reject", -0.5)

    def _count():
        with get_connection(db) as conn:
            return conn.execute("SELECT COUNT(*) c FROM lessons_learned").fetchone()["c"]

    before = _count()
    FailureClassifier(db_path=db).classify_all()
    assert _count() == before


# --- schema ---------------------------------------------------------------

def test_projection_table_exists_and_is_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='failure_reason'"
        ).fetchone() is not None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE failure_reason")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='failure_reason'"
        ).fetchone() is not None
