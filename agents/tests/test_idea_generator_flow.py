"""End-to-end M6 flow with FakeIdeaLLM: propose -> validate -> queue -> approve.

Verifies logging payloads land in agent_conversations and that NOTHING is
executed (no experiments row written, Runner/Critic never touched).
"""

import json

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage.conversation_store import get_messages_by_type
from agents.idea_generator.llm_client import FakeIdeaLLM
from agents.idea_generator import approval_queue as q
from agents.idea_generator import idea_runner


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "flow.db"
    create_all_tables(path)
    return path


def _valid_payload():
    return json.dumps({"ideas": [{
        "hypothesis": "Calm regimes strengthen momentum",
        "suggested_signals": ["mom_ret_20", "low_vol_20"],
        "rationale": "vol-scaled momentum",
    }]})


def _invalid_payload():
    return json.dumps({"ideas": [{
        "hypothesis": "Uses a bogus signal",
        "suggested_signals": ["totally_made_up"],
    }]})


def test_valid_idea_flows_to_pending_and_logs_proposed(db):
    out = idea_runner.run_idea_batch(
        FakeIdeaLLM(responses=[_valid_payload()]),
        cycle_id="cycle_001", market="us", universe="sp500", db_path=db,
    )
    assert len(out.pending) == 1
    assert out.rejected == []
    proposed = get_messages_by_type("cycle_001", "idea_proposed", db_path=db)
    assert len(proposed) == 1
    p = proposed[0]["payload"]
    assert p["source_model"] == "fake-idea-llm"
    assert p["validation"]["ok"] is True
    assert "scores" in p


def test_invalid_idea_is_rejected_and_logged(db):
    out = idea_runner.run_idea_batch(
        FakeIdeaLLM(responses=[_invalid_payload()]),
        cycle_id="cycle_002", db_path=db,
    )
    assert out.pending == []
    assert len(out.rejected) == 1
    rejected = get_messages_by_type("cycle_002", "idea_rejected", db_path=db)
    assert len(rejected) == 1
    reasons = rejected[0]["payload"]["validation"]["reasons"]
    assert any("unknown_signal" in r for r in reasons)


def test_parse_failure_is_rejected_not_raised(db):
    out = idea_runner.run_idea_batch(
        FakeIdeaLLM(responses=["not json at all"]),
        cycle_id="cycle_003", db_path=db,
    )
    assert out.pending == []
    assert len(out.rejected) == 1
    rejected = get_messages_by_type("cycle_003", "idea_rejected", db_path=db)
    assert rejected[0]["payload"]["stage"] == "parse"


def test_approve_logs_idea_approved(db):
    idea_runner.run_idea_batch(
        FakeIdeaLLM(responses=[_valid_payload()]),
        cycle_id="cycle_004", db_path=db,
    )
    iid = q.list_pending(db_path=db)[0]["idea_id"]
    assert idea_runner.approve(iid, note="ship it", db_path=db) is True
    approved = get_messages_by_type("cycle_004", "idea_approved", db_path=db)
    assert len(approved) == 1
    assert approved[0]["payload"]["idea_id"] == iid


def test_flow_writes_no_experiment_row(db):
    idea_runner.run_idea_batch(
        FakeIdeaLLM(responses=[_valid_payload()]),
        cycle_id="cycle_005", db_path=db,
    )
    with get_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    assert n == 0  # M6 never executes or persists an experiment


def test_duplicate_idea_within_known_experiments_rejected(db):
    # Seed an experiment with the same hypothesis.
    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO experiments (experiment_id, hypothesis) VALUES (?, ?)",
            ("exp_1", "Calm regimes strengthen momentum"),
        )
        conn.commit()
    out = idea_runner.run_idea_batch(
        FakeIdeaLLM(responses=[_valid_payload()]),
        cycle_id="cycle_006", db_path=db,
    )
    assert out.pending == []
    assert len(out.rejected) == 1
