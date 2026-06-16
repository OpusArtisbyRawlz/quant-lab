"""Tests for agents/ledger_agent/ledger_agent.py."""

import pytest
from pathlib import Path

from agents.protocol import CritiqueResult, LedgerUpdate
from agents.ledger_agent.ledger_agent import LedgerAgent
from agents.experiment_runner.runner import RunResult
from agents.storage.ledger_store import get_experiment, upsert_experiment
from agents.storage.lessons_store import get_lessons_for_experiment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _success_result(experiment_id="exp_001") -> RunResult:
    return RunResult(
        experiment_id=experiment_id,
        status="success",
        metrics={"sharpe": 1.2, "mdd": -0.15, "cagr": 0.20, "vol": 0.12, "calmar": 2.0},
        artifact_path=None,
    )


def _failed_result(experiment_id="exp_001") -> RunResult:
    return RunResult(
        experiment_id=experiment_id,
        status="failed",
        metrics={},
        artifact_path=None,
        error="ValueError: pipeline crashed",
    )


def _critique(decision="keep", passed=True) -> CritiqueResult:
    return CritiqueResult(
        experiment_id="exp_001",
        passed=passed,
        drawdown_flag=False,
        decision=decision,
        notes="✓ Sharpe: actual=1.2000  threshold=≥0.5000 [config]",
        thresholds_used={"minimum_sharpe": {"value": 0.5, "source": "config"}},
    )


# ---------------------------------------------------------------------------
# LedgerUpdate return value
# ---------------------------------------------------------------------------

def test_ledger_agent_returns_ledger_update(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    result = LedgerAgent().run(_success_result(), _critique(), db_path=tmp_db)
    assert isinstance(result, LedgerUpdate)


def test_ledger_agent_experiment_id_in_update(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    result = LedgerAgent().run(_success_result(), _critique(), db_path=tmp_db)
    assert result.experiment_id == "exp_001"


def test_ledger_agent_decision_propagated(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    result = LedgerAgent().run(_success_result(), _critique(decision="reject", passed=False), db_path=tmp_db)
    assert result.decision == "reject"


def test_ledger_agent_lesson_written_true_on_success(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    result = LedgerAgent().run(_success_result(), _critique(), db_path=tmp_db)
    assert result.lesson_written is True


def test_ledger_agent_conclusion_non_empty(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    result = LedgerAgent().run(_success_result(), _critique(), db_path=tmp_db)
    assert result.conclusion


# ---------------------------------------------------------------------------
# DB writes — experiments table
# ---------------------------------------------------------------------------

def test_ledger_agent_writes_decision_to_db(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    LedgerAgent().run(_success_result(), _critique(decision="keep"), db_path=tmp_db)
    row = get_experiment("exp_001", db_path=tmp_db)
    assert row["decision"] == "keep"


def test_ledger_agent_writes_reject_decision(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    LedgerAgent().run(_success_result(), _critique(decision="reject", passed=False), db_path=tmp_db)
    row = get_experiment("exp_001", db_path=tmp_db)
    assert row["decision"] == "reject"


def test_ledger_agent_writes_retest_for_pipeline_failure(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    critique = CritiqueResult(
        experiment_id="exp_001", passed=False, drawdown_flag=False,
        decision="retest", notes="Pipeline failed.",
        thresholds_used={},
    )
    LedgerAgent().run(_failed_result(), critique, db_path=tmp_db)
    row = get_experiment("exp_001", db_path=tmp_db)
    assert row["decision"] == "retest"


# ---------------------------------------------------------------------------
# DB writes — lessons_learned table
# ---------------------------------------------------------------------------

def test_ledger_agent_writes_lesson(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    LedgerAgent().run(_success_result(), _critique(), db_path=tmp_db)
    lessons = get_lessons_for_experiment("exp_001", db_path=tmp_db)
    assert len(lessons) >= 1


def test_ledger_agent_keep_lesson_category_is_signal_quality(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    LedgerAgent().run(_success_result(), _critique(decision="keep"), db_path=tmp_db)
    lessons = get_lessons_for_experiment("exp_001", db_path=tmp_db)
    assert lessons[0]["category"] == "signal_quality"


def test_ledger_agent_reject_lesson_category_is_signal_quality(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    LedgerAgent().run(_success_result(), _critique(decision="reject", passed=False), db_path=tmp_db)
    lessons = get_lessons_for_experiment("exp_001", db_path=tmp_db)
    assert lessons[0]["category"] == "signal_quality"


def test_ledger_agent_retest_lesson_category_is_pipeline(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    critique = CritiqueResult(
        experiment_id="exp_001", passed=False, drawdown_flag=False,
        decision="retest", notes="Pipeline failed.", thresholds_used={},
    )
    LedgerAgent().run(_failed_result(), critique, db_path=tmp_db)
    lessons = get_lessons_for_experiment("exp_001", db_path=tmp_db)
    assert lessons[0]["category"] == "pipeline"


def test_ledger_agent_lesson_finding_contains_experiment_id(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    LedgerAgent().run(_success_result(), _critique(), db_path=tmp_db)
    lessons = get_lessons_for_experiment("exp_001", db_path=tmp_db)
    assert "exp_001" in lessons[0]["finding"]


def test_ledger_agent_lesson_category_in_update(tmp_db):
    upsert_experiment({"experiment_id": "exp_001"}, db_path=tmp_db)
    update = LedgerAgent().run(_success_result(), _critique(), db_path=tmp_db)
    assert update.lesson_category == "signal_quality"
