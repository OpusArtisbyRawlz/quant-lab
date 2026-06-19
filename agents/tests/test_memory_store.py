"""Tests for memory_store — research_memory writes/reads (Milestone 9)."""

from agents.storage import memory_store as ms


def test_add_and_list(tmp_db):
    ms.add_memory("India/NIFTY50/high_vol", "mom20 strong",
                  implication="prioritise", confidence="medium", db_path=tmp_db)
    rows = ms.list_memory(scope_key="India/NIFTY50/high_vol", db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["finding"] == "mom20 strong"
    assert rows[0]["embedding"] is None  # offline/test path keeps embedding NULL


def test_add_is_idempotent_on_scope_and_finding(tmp_db):
    ms.add_memory("k", "same finding", implication="a", db_path=tmp_db)
    ms.add_memory("k", "same finding", implication="b", db_path=tmp_db)
    rows = ms.list_memory(scope_key="k", db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["implication"] == "b"  # update-in-place


def test_memory_for_idea_generator_returns_all_scopes(tmp_db):
    ms.add_memory("k1", "f1", db_path=tmp_db)
    ms.add_memory("k2", "f2", db_path=tmp_db)
    rows = ms.memory_for_idea_generator(db_path=tmp_db)
    assert {r["finding"] for r in rows} == {"f1", "f2"}
