"""
M11 PR-11 — decision-record explainability (builders + ExplanationWriter).

Proves the pure builders shape projection rows into decision records, and that the
writer is a pure, replay-deterministic, idempotent fold of the existing M11
projections into ``decision_record`` — recomputing nothing and mutating no evidence.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import evidence_store, decision_record_store
from agents.research_intelligence import (
    EvidenceProjector, PromotionEngine, RetirementEngine, FdrEngine,
    FailureClassifier, ExplanationWriter, explanation,
)


# --- pure builders --------------------------------------------------------

def test_build_promotion_record_shape():
    reco = {"hypothesis_id": "H", "recommended_stage": "Validated", "promotion_tier": 2,
            "confidence_score": 0.97, "q_precision": 0.8, "r_sign": 0.9, "r_disp": 0.7,
            "r_replicas": 0.8, "g_count": 3, "g_coverage": 0.6, "v_net_sharpe": 1.1,
            "v_ci_low": 0.6, "gate_detail": [], "method": "promotion_v1"}
    rec = explanation.build_promotion_record(reco, ["E1", "E2"], ["E3"])
    assert rec["decision_type"] == "promote" and rec["subject_id"] == "H"
    assert rec["chosen"] == {"stage": "Validated", "tier": 2}
    assert rec["confidence"] == 0.97
    assert rec["supporting_experiment_ids"] == ["E1", "E2"]
    assert rec["contradictory_experiment_ids"] == ["E3"]
    assert rec["policy_version"] == "promotion_v1"


def test_build_rejection_record_shape():
    failure = {"experiment_id": "E9", "reason_code": "no_edge",
               "evidence": {"net_sharpe": -0.5}, "method": "failure_v1"}
    rec = explanation.build_rejection_record(failure)
    assert rec["decision_type"] == "reject" and rec["subject_id"] == "E9"
    assert rec["chosen"] == {"reason_code": "no_edge"}
    assert rec["policy_version"] == "failure_v1"


# --- ExplanationWriter engine --------------------------------------------

def _fresh_db(tmp_path, name="expl.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db, hid, n, s, start=0, decision=None, yr0=2005):
    for i in range(n):
        j = start + i
        evidence_store.record_evidence(
            f"{hid}-{j}", hypothesis_id=hid, market="IN", universe="NIFTY",
            regime="all", bar_type="time",
            date_start=f"{yr0+j}-01-01", date_end=f"{yr0+j}-12-31",
            metrics={"net_sharpe": s, "T": 2520, "N": 252, "K": 1},
            critic_decision=decision, db_path=db)


def _build(db):
    EvidenceProjector(db_path=db).rebuild_all()
    FdrEngine(db_path=db).rebuild_all()
    RetirementEngine(db_path=db).rebuild_all()
    PromotionEngine(db_path=db).rebuild_all()
    FailureClassifier(db_path=db).classify_all()
    return ExplanationWriter(db_path=db).rebuild_all()


def _no_ts(row):
    row = dict(row)
    row.pop("created_at", None)
    return row


def test_writer_emits_promote_retire_reject(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hgood", 8, 1.4)
    _seed(db, "Hbad", 8, -1.5, decision="reject")
    counts = _build(db)
    assert counts["promote"] == 2                # one per hypothesis recommendation
    assert counts["retire"] == 1                 # Hbad refuted
    assert counts["reject"] == 8                 # Hbad's 8 rejected experiments
    assert decision_record_store.get_record("retire", "Hbad", db_path=db) is not None
    assert decision_record_store.get_record("promote", "Hgood", db_path=db) is not None


def test_supporting_contradictory_split_by_sign(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "H", 6, 1.2, start=0)              # positive → supporting
    _seed(db, "H", 4, -0.8, start=100)           # negative → contradictory
    _build(db)
    rec = decision_record_store.get_record("promote", "H", db_path=db)
    assert len(rec["supporting_experiment_ids"]) == 6
    assert len(rec["contradictory_experiment_ids"]) == 4


# --- determinism ----------------------------------------------------------

def test_rebuild_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hbad", 8, -1.5, decision="reject")
    _build(db)
    first = [_no_ts(r) for r in decision_record_store.list_records(db_path=db)]
    ExplanationWriter(db_path=db).rebuild_all()
    second = [_no_ts(r) for r in decision_record_store.list_records(db_path=db)]
    assert first == second


def test_replay_deterministic_across_insertion_order(tmp_path):
    def build(reverse, name):
        db = _fresh_db(tmp_path, name)
        specs = [("Ha", 6, 1.2, 0, None), ("Hb", 8, -1.5, 100, "reject")]
        for hid, n, s, start, dec in (reversed(specs) if reverse else specs):
            _seed(db, hid, n, s, start=start, decision=dec)
        _build(db)
        return [_no_ts(r) for r in decision_record_store.list_records(db_path=db)]

    assert build(False, "a.db") == build(True, "b.db")


def test_prune_removes_stale_record(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hbad", 8, -1.5, decision="reject")
    _build(db)
    # Insert a decision record whose subject is not in any projection.
    decision_record_store.upsert_record(
        {"decision_type": "promote", "subject_id": "GHOST"}, db_path=db)
    ExplanationWriter(db_path=db).rebuild_all()
    assert decision_record_store.get_record("promote", "GHOST", db_path=db) is None


def test_evidence_events_are_never_mutated(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hbad", 8, -1.5, decision="reject")
    EvidenceProjector(db_path=db).rebuild_all()

    def _snapshot():
        with get_connection(db) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT * FROM evidence_event ORDER BY id").fetchall()]

    before = _snapshot()
    _build(db)
    ExplanationWriter(db_path=db).rebuild_all()
    assert _snapshot() == before


def test_versioning_from_source_engines(tmp_path):
    db = _fresh_db(tmp_path)
    _seed(db, "Hbad", 8, -1.5, decision="reject")
    _build(db)
    assert decision_record_store.get_record("promote", "Hbad", db_path=db)["policy_version"] == "promotion_v1"
    assert decision_record_store.get_record("retire", "Hbad", db_path=db)["policy_version"] == "retirement_v1"
    assert decision_record_store.get_record("reject", "Hbad-0", db_path=db)["policy_version"] == "failure_v1"


# --- schema ---------------------------------------------------------------

def test_projection_table_exists_and_is_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='decision_record'"
        ).fetchone() is not None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE decision_record")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='decision_record'"
        ).fetchone() is not None
