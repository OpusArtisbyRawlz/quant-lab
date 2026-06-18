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


def _idea(h="Test hypothesis"):
    return ProposedIdea(
        hypothesis=h,
        suggested_signals=("mom_ret_5",),
        source_model="fake-idea-llm",
        rationale="because",
        scores={"novelty_score": 0.5, "feasibility_score": 0.8, "signal_diversity_score": 0.3},
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
