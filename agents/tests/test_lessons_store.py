"""Tests for lessons_store.py — lessons_learned table."""

import pytest
from agents.storage import ledger_store as ls
from agents.storage import lessons_store as lo


def _seed_experiment(db_path, exp_id="EXP_TEST_001"):
    ls.upsert_experiment({
        "experiment_id": exp_id,
        "project": "test_project",
        "status": "completed",
    }, db_path=db_path)


def test_add_lesson(tmp_db):
    _seed_experiment(tmp_db)
    row_id = lo.add_lesson(
        experiment_id="EXP_TEST_001",
        finding="Momentum decays after 20 days",
        implication="Prefer 10d lookback in low-vol environments",
        category="signal",
        confidence="high",
        cycle_id="CYCLE_001",
        db_path=tmp_db,
    )
    assert row_id > 0


def test_get_lessons_for_experiment(tmp_db):
    _seed_experiment(tmp_db)
    lo.add_lesson("EXP_TEST_001", "Finding A", "Implication A", db_path=tmp_db)
    lo.add_lesson("EXP_TEST_001", "Finding B", "Implication B", db_path=tmp_db)
    lessons = lo.get_lessons_for_experiment("EXP_TEST_001", db_path=tmp_db)
    assert len(lessons) == 2
    assert lessons[0]["finding"] == "Finding A"


def test_bulk_add_lessons(tmp_db):
    _seed_experiment(tmp_db)
    data = [
        {"experiment_id": "EXP_TEST_001", "finding": f"Bulk finding {i}",
         "implication": f"Implication {i}", "category": "risk", "confidence": "medium"}
        for i in range(5)
    ]
    count = lo.bulk_add_lessons(data, db_path=tmp_db)
    assert count == 5
    lessons = lo.get_lessons_for_experiment("EXP_TEST_001", db_path=tmp_db)
    assert len(lessons) == 5


def test_list_lessons_filter_category(tmp_db):
    _seed_experiment(tmp_db)
    lo.add_lesson("EXP_TEST_001", "Signal finding", "sig implication", category="signal", db_path=tmp_db)
    lo.add_lesson("EXP_TEST_001", "Risk finding", "risk implication", category="risk", db_path=tmp_db)

    signal_lessons = lo.list_lessons(category="signal", db_path=tmp_db)
    assert all(l["category"] == "signal" for l in signal_lessons)
    assert len(signal_lessons) == 1


def test_list_lessons_filter_confidence(tmp_db):
    _seed_experiment(tmp_db)
    lo.add_lesson("EXP_TEST_001", "High conf", "implication", confidence="high", db_path=tmp_db)
    lo.add_lesson("EXP_TEST_001", "Low conf", "implication", confidence="low", db_path=tmp_db)

    high = lo.list_lessons(confidence="high", db_path=tmp_db)
    assert all(l["confidence"] == "high" for l in high)


def test_get_high_confidence_lessons(tmp_db):
    _seed_experiment(tmp_db)
    lo.add_lesson("EXP_TEST_001", "High A", "imp A", confidence="high", db_path=tmp_db)
    lo.add_lesson("EXP_TEST_001", "Medium B", "imp B", confidence="medium", db_path=tmp_db)
    high = lo.get_high_confidence_lessons(db_path=tmp_db)
    assert all(l["confidence"] == "high" for l in high)


def test_lessons_for_idea_generator_ordering(tmp_db):
    _seed_experiment(tmp_db)
    lo.add_lesson("EXP_TEST_001", "Low", "imp", confidence="low", db_path=tmp_db)
    lo.add_lesson("EXP_TEST_001", "High", "imp", confidence="high", db_path=tmp_db)
    lo.add_lesson("EXP_TEST_001", "Medium", "imp", confidence="medium", db_path=tmp_db)

    lessons = lo.lessons_for_idea_generator(db_path=tmp_db)
    confidences = [l["confidence"] for l in lessons]
    # high must come before medium, medium before low
    assert confidences.index("high") < confidences.index("medium")
    assert confidences.index("medium") < confidences.index("low")


def test_lesson_summary(tmp_db):
    _seed_experiment(tmp_db)
    lo.add_lesson("EXP_TEST_001", "F1", "I1", category="signal", confidence="high", db_path=tmp_db)
    lo.add_lesson("EXP_TEST_001", "F2", "I2", category="risk", confidence="medium", db_path=tmp_db)
    summary = lo.lesson_summary(db_path=tmp_db)
    assert summary["total"] == 2
    assert "signal" in summary["by_category"]
    assert "high" in summary["by_confidence"]


def test_lesson_requires_valid_experiment(tmp_db):
    """Inserting a lesson for a non-existent experiment must fail (FK constraint)."""
    with pytest.raises(Exception):
        lo.add_lesson("NONEXISTENT_EXP", "finding", "implication", db_path=tmp_db)
