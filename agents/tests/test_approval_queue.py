"""Tests for the SQLite-backed approval queue."""

import pytest

from agents.storage.db import create_all_tables
from agents.protocol import ProposedIdea
from agents.idea_generator import approval_queue as q


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "ideas.db"
    create_all_tables(path)
    return path


def _idea(h="Test hypothesis", market="us", universe="sp500"):
    return ProposedIdea(
        hypothesis=h,
        suggested_signals=("mom_ret_5",),
        source_model="fake-idea-llm",
        rationale="because",
        scores={"novelty_score": 0.5, "feasibility_score": 0.8, "signal_diversity_score": 0.3},
        market=market,
        universe=universe,
    )


def test_enqueue_and_list_pending(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, cycle_id="cycle_001", db_path=db)
    pending = q.list_pending(db_path=db)
    assert len(pending) == 1
    row = pending[0]
    assert row["status"] == "pending"
    assert row["source_model"] == "fake-idea-llm"
    assert row["suggested_signals"] == ["mom_ret_5"]
    assert row["metadata"]["scores"]["feasibility_score"] == 0.8


def test_approve_marks_approved_and_sets_reviewed_at(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    assert q.approve_idea(iid, note="looks good", db_path=db) is True
    rec = q.get_idea(iid, db_path=db)
    assert rec["status"] == "approved"
    assert rec["reviewed_at"] is not None
    assert rec["reviewer_note"] == "looks good"
    assert q.list_pending(db_path=db) == []


def test_reject_marks_rejected(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    assert q.reject_idea(iid, note="nope", db_path=db) is True
    assert q.get_idea(iid, db_path=db)["status"] == "rejected"


def test_approve_is_idempotent(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    assert q.approve_idea(iid, db_path=db) is True
    assert q.approve_idea(iid, db_path=db) is False  # already decided


def test_record_rejected_persists_reasons(db):
    idea = _idea("bad idea")
    iid = q.make_idea_id(idea, db_path=db)
    q.record_rejected(idea, iid, ["unknown_signal(s): ['x']"], db_path=db)
    rec = q.get_idea(iid, db_path=db)
    assert rec["status"] == "rejected"
    assert rec["validation_ok"] == 0
    assert "unknown_signal" in rec["validation_reasons"][0]


def test_persistence_survives_reconnect(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    # A brand-new call (new connection) still sees the row.
    assert q.get_idea(iid, db_path=db)["hypothesis"] == "Test hypothesis"


def test_ids_increment(db):
    i1 = q.make_idea_id(_idea("one"), db_path=db)
    q.enqueue(_idea("one"), i1, db_path=db)
    i2 = q.make_idea_id(_idea("two"), db_path=db)
    assert i1.startswith("idea_001")
    assert i2.startswith("idea_002")


# --- M7: market/universe persistence + approved/executed lifecycle ---------

def test_market_universe_persisted_on_enqueue(db):
    iid = q.make_idea_id(_idea(market="eu", universe="stoxx600"), db_path=db)
    q.enqueue(_idea(market="eu", universe="stoxx600"), iid, db_path=db)
    rec = q.get_idea(iid, db_path=db)
    assert rec["market"] == "eu"
    assert rec["universe"] == "stoxx600"


def test_blank_market_universe_default_to_unknown(db):
    iid = q.make_idea_id(_idea(market="", universe=""), db_path=db)
    q.enqueue(_idea(market="", universe=""), iid, db_path=db)
    rec = q.get_idea(iid, db_path=db)
    assert rec["market"] == "unknown"
    assert rec["universe"] == "unknown"


def test_list_approved_and_get_approved(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    assert q.list_approved(db_path=db) == []
    assert q.get_approved(iid, db_path=db) is None  # still pending
    q.approve_idea(iid, db_path=db)
    assert len(q.list_approved(db_path=db)) == 1
    assert q.get_approved(iid, db_path=db)["idea_id"] == iid


def test_claim_for_execution_is_atomic_cas(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    q.approve_idea(iid, db_path=db)
    # First claim wins; second loses (idempotent CAS on status).
    assert q.claim_for_execution(iid, db_path=db) is True
    assert q.get_idea(iid, db_path=db)["status"] == "executing"
    assert q.claim_for_execution(iid, db_path=db) is False
    # Claimed ideas are not drained as approved.
    assert q.list_approved(db_path=db) == []
    assert len(q.list_executing(db_path=db)) == 1


def test_mark_executed_transitions_and_links(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    q.approve_idea(iid, db_path=db)
    q.claim_for_execution(iid, db_path=db)
    assert q.mark_executed(iid, "exp_001_x", db_path=db) is True
    rec = q.get_idea(iid, db_path=db)
    assert rec["status"] == "executed"
    assert rec["experiment_id"] == "exp_001_x"
    # Idempotent: re-running on a non-executing row is a no-op.
    assert q.mark_executed(iid, "exp_001_x", db_path=db) is False


def test_mark_executed_requires_executing(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    q.approve_idea(iid, db_path=db)
    # Approved but not yet claimed — cannot jump straight to executed.
    assert q.mark_executed(iid, "exp_001_x", db_path=db) is False


def test_link_experiment_only_while_executing(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    q.approve_idea(iid, db_path=db)
    assert q.link_experiment(iid, "exp_001_x", db_path=db) is False  # not executing
    q.claim_for_execution(iid, db_path=db)
    assert q.link_experiment(iid, "exp_001_x", db_path=db) is True
    rec = q.get_idea(iid, db_path=db)
    assert rec["experiment_id"] == "exp_001_x"
    assert rec["status"] == "executing"  # link does not complete


def test_reject_executing_transitions_only_executing(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    q.approve_idea(iid, db_path=db)
    assert q.reject_executing(iid, note="x", db_path=db) is False  # still approved
    q.claim_for_execution(iid, db_path=db)
    assert q.reject_executing(iid, note="bad spec", db_path=db) is True
    assert q.get_idea(iid, db_path=db)["status"] == "rejected"


def test_reject_approved_transitions_only_approved(db):
    iid = q.make_idea_id(_idea(), db_path=db)
    q.enqueue(_idea(), iid, db_path=db)
    # Pending row is not touched by reject_approved.
    assert q.reject_approved(iid, note="bad", db_path=db) is False
    q.approve_idea(iid, db_path=db)
    assert q.reject_approved(iid, note="exec failed", db_path=db) is True
    rec = q.get_idea(iid, db_path=db)
    assert rec["status"] == "rejected"
    assert rec["reviewer_note"] == "exec failed"
