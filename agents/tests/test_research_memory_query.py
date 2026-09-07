"""
M11 PR-11 — research_memory_query read-models (pure readers over projections).

Proves the standing-question / board readers answer purely from the stored
projections, deterministically, and are empty on an empty database.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables
from agents.storage import evidence_store
from agents.research_intelligence import (
    EvidenceProjector, PromotionEngine, RetirementEngine, FdrEngine,
    GeneralisationProjector, FailureClassifier, ExplanationWriter,
    research_memory_query as q,
)


def _fresh_db(tmp_path):
    db = tmp_path / "q.db"
    create_all_tables(db)
    return db


def _seed(db, hid, market, regime, n, s, start=0, decision=None, flags=None, yr0=2005):
    for i in range(n):
        evidence_store.record_evidence(
            f"{hid}-{market}-{regime}-{i}", hypothesis_id=hid, market=market,
            universe="NIFTY", regime=regime, bar_type="time",
            date_start=f"{yr0+i}-01-01", date_end=f"{yr0+i}-12-31",
            metrics={"net_sharpe": s, "T": 2520, "N": 252, "K": 1},
            critic_decision=decision, robustness_flags=flags, db_path=db)


def _build(db):
    EvidenceProjector(db_path=db).rebuild_all()
    FdrEngine(db_path=db).rebuild_all()
    RetirementEngine(db_path=db).rebuild_all()
    PromotionEngine(db_path=db).rebuild_all()
    GeneralisationProjector(db_path=db).rebuild_all()
    FailureClassifier(db_path=db).classify_all()
    ExplanationWriter(db_path=db).rebuild_all()


def _populated(db):
    _seed(db, "Hstar", "IN", "low_vol", 12, 1.6, start=0)
    _seed(db, "Hstar", "US", "high_vol", 12, 1.6, start=100)
    _seed(db, "Hbad", "IN", "all", 8, -1.5, start=300, decision="reject")
    _build(db)


# --- boards ---------------------------------------------------------------

def test_stage_board_lists_every_hypothesis(tmp_path):
    db = _fresh_db(tmp_path)
    _populated(db)
    board = {r["hypothesis_id"]: r for r in q.stage_board(db_path=db)}
    assert set(board) == {"Hstar", "Hbad"}
    assert board["Hstar"]["stage"] in ("Validated", "Production Candidate", "Promising")
    assert 0.0 <= board["Hstar"]["confidence"] <= 1.0


def test_retirement_log_lists_retired(tmp_path):
    db = _fresh_db(tmp_path)
    _populated(db)
    log = q.retirement_log(db_path=db)
    assert [r["hypothesis_id"] for r in log] == ["Hbad"]
    assert log[0]["state"] == "Retired-Refuted"


def test_generalisation_board(tmp_path):
    db = _fresh_db(tmp_path)
    _populated(db)
    rows = q.generalisation_board("Hstar", db_path=db)
    assert {r["dimension"] for r in rows} == {"market", "universe", "regime", "bar_type", "period"}


# --- standing questions ---------------------------------------------------

def test_surviving_hypotheses(tmp_path):
    db = _fresh_db(tmp_path)
    _populated(db)
    assert q.surviving_hypotheses(db_path=db) == ["Hstar"]     # Hbad has no passing cells


def test_market_transfer(tmp_path):
    db = _fresh_db(tmp_path)
    _populated(db)
    mt = q.market_transfer("Hstar", db_path=db)
    assert mt["markets_passing"] == 2 and mt["markets_available"] == 2


def test_overfit_experiments(tmp_path):
    db = _fresh_db(tmp_path)
    # A positive-Sharpe but cost-fragile rejected experiment → overfit bucket.
    _seed(db, "Hof", "IN", "all", 6, 1.2, start=0, decision="reject", flags=["cost_fragility"])
    _build(db)
    of = q.overfit_experiments(db_path=db)
    assert of and all(r["reason_code"] == "cost_fragility" for r in of)


def test_failure_summary(tmp_path):
    db = _fresh_db(tmp_path)
    _populated(db)
    summary = q.failure_summary(db_path=db)
    assert summary.get("no_edge", 0) == 8          # Hbad's 8 negative experiments


def test_explanations_for_subject(tmp_path):
    db = _fresh_db(tmp_path)
    _populated(db)
    recs = {r["decision_type"] for r in q.explanations_for("Hbad", db_path=db)}
    assert {"promote", "retire"} <= recs


# --- purity / empty -------------------------------------------------------

def test_readers_are_deterministic(tmp_path):
    db = _fresh_db(tmp_path)
    _populated(db)
    assert q.stage_board(db_path=db) == q.stage_board(db_path=db)
    assert q.failure_summary(db_path=db) == q.failure_summary(db_path=db)


def test_empty_database_returns_empty(tmp_path):
    db = _fresh_db(tmp_path)
    assert q.stage_board(db_path=db) == []
    assert q.retirement_log(db_path=db) == []
    assert q.surviving_hypotheses(db_path=db) == []
    assert q.failure_summary(db_path=db) == {}
    assert q.market_transfer("nope", db_path=db) is None
