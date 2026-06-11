"""Tests for conversation_store.py — agent_conversations table."""

import pytest
from agents.storage import conversation_store as cs


CYCLE = "CYCLE_001"


def _msg(sender="commander", recipient="idea_generator", mtype="hypothesis",
         payload=None, cycle_id=CYCLE):
    return {
        "cycle_id": cycle_id,
        "sender": sender,
        "recipient": recipient,
        "message_type": mtype,
        "payload": payload or {"text": "test message"},
    }


def test_log_message(tmp_db):
    row_id = cs.log_message(
        cycle_id=CYCLE,
        sender="commander",
        recipient="idea_generator",
        message_type="hypothesis",
        payload={"hypothesis": "Momentum beats reversal"},
        db_path=tmp_db,
    )
    assert row_id > 0


def test_get_cycle_messages(tmp_db):
    cs.log_message(CYCLE, "commander", "idea_generator", "hypothesis",
                   {"h": "a"}, db_path=tmp_db)
    cs.log_message(CYCLE, "idea_generator", "designer", "spec",
                   {"features": ["mom"]}, db_path=tmp_db)
    msgs = cs.get_cycle_messages(CYCLE, db_path=tmp_db)
    assert len(msgs) == 2
    assert msgs[0]["sender"] == "commander"
    assert isinstance(msgs[0]["payload"], dict)


def test_get_messages_by_type(tmp_db):
    cs.log_message(CYCLE, "commander", "idea_generator", "hypothesis", {}, db_path=tmp_db)
    cs.log_message(CYCLE, "idea_generator", "designer", "spec", {}, db_path=tmp_db)
    cs.log_message(CYCLE, "designer", "backtest", "spec", {}, db_path=tmp_db)

    specs = cs.get_messages_by_type(CYCLE, "spec", db_path=tmp_db)
    assert len(specs) == 2
    assert all(m["message_type"] == "spec" for m in specs)


def test_list_cycles(tmp_db):
    cs.log_message("CYCLE_A", "a", "b", "hypothesis", {}, db_path=tmp_db)
    cs.log_message("CYCLE_B", "a", "b", "hypothesis", {}, db_path=tmp_db)
    cycles = cs.list_cycles(db_path=tmp_db)
    assert set(cycles) == {"CYCLE_A", "CYCLE_B"}


def test_get_latest_cycle(tmp_db):
    cs.log_message("CYCLE_FIRST", "a", "b", "hypothesis", {}, db_path=tmp_db)
    cs.log_message("CYCLE_SECOND", "a", "b", "hypothesis", {}, db_path=tmp_db)
    latest = cs.get_latest_cycle(db_path=tmp_db)
    # Most recently inserted is CYCLE_SECOND
    assert latest == "CYCLE_SECOND"


def test_get_latest_cycle_empty_db(tmp_db):
    assert cs.get_latest_cycle(db_path=tmp_db) is None


def test_log_many(tmp_db):
    messages = [_msg(mtype=t) for t in ["hypothesis", "spec", "result", "critique"]]
    count = cs.log_many(messages, db_path=tmp_db)
    assert count == 4
    msgs = cs.get_cycle_messages(CYCLE, db_path=tmp_db)
    assert len(msgs) == 4


def test_payload_roundtrip(tmp_db):
    """Complex nested payload must survive JSON serialization."""
    payload = {
        "features": ["mom_20d", "vol_10d"],
        "metrics": {"sharpe": 1.4, "mdd": -0.25},
        "nested": {"a": [1, 2, 3]},
    }
    cs.log_message(CYCLE, "backtest", "critic", "result", payload, db_path=tmp_db)
    msgs = cs.get_cycle_messages(CYCLE, db_path=tmp_db)
    assert msgs[0]["payload"] == payload


def test_conversation_summary(tmp_db):
    cs.log_message(CYCLE, "commander", "idea_generator", "hypothesis", {}, db_path=tmp_db)
    cs.log_message(CYCLE, "backtest", "critic", "result", {}, db_path=tmp_db)
    cs.log_message("CYCLE_002", "commander", "idea_generator", "hypothesis", {}, db_path=tmp_db)

    summary = cs.conversation_summary(db_path=tmp_db)
    assert summary["total_messages"] == 3
    assert summary["total_cycles"] == 2
    assert summary["by_type"]["hypothesis"] == 2
    assert summary["by_sender"]["commander"] == 2


def test_messages_isolated_by_cycle(tmp_db):
    cs.log_message("CYCLE_X", "a", "b", "hypothesis", {"n": 1}, db_path=tmp_db)
    cs.log_message("CYCLE_Y", "a", "b", "hypothesis", {"n": 2}, db_path=tmp_db)
    x_msgs = cs.get_cycle_messages("CYCLE_X", db_path=tmp_db)
    y_msgs = cs.get_cycle_messages("CYCLE_Y", db_path=tmp_db)
    assert len(x_msgs) == 1
    assert len(y_msgs) == 1
