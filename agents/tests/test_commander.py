"""Tests for agents/commander/commander.py."""

import pytest
from pathlib import Path

from agents.protocol import ResearchAgenda, HypothesisTask
from agents.commander.commander import Commander
from agents.storage.db import create_all_tables
from agents.storage.ledger_store import upsert_experiment


@pytest.fixture
def agenda():
    return ResearchAgenda(
        hypotheses=[
            "mr_ret_5 mean-reversion works on short horizons",
            "low_vol_20 captures low-volatility premium",
            "mom_ret_10 momentum persists over medium horizons",
        ],
        project="project_test",
        universe="test_universe",
        market="US",
    )


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

def test_commander_returns_list(tmp_db, agenda):
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert isinstance(tasks, list)


def test_commander_all_tasks_are_hypothesis_task(tmp_db, agenda):
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert all(isinstance(t, HypothesisTask) for t in tasks)


def test_commander_task_count_matches_hypotheses(tmp_db, agenda):
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert len(tasks) == 3


def test_commander_hypothesis_text_preserved(tmp_db, agenda):
    tasks = Commander().run(agenda, db_path=tmp_db)
    task_hyps = {t.hypothesis for t in tasks}
    assert task_hyps == set(agenda.hypotheses)


def test_commander_project_propagated(tmp_db, agenda):
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert all(t.project == "project_test" for t in tasks)


def test_commander_universe_propagated(tmp_db, agenda):
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert all(t.universe == "test_universe" for t in tasks)


def test_commander_market_propagated(tmp_db, agenda):
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert all(t.market == "US" for t in tasks)


# ---------------------------------------------------------------------------
# Signal extraction from hypothesis text
# ---------------------------------------------------------------------------

def test_commander_extracts_signal_from_text(tmp_db):
    agenda = ResearchAgenda(
        hypotheses=["mr_ret_5 works well"],
        project="p", universe="u", market="US",
    )
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert "mr_ret_5" in tasks[0].suggested_signals


def test_commander_no_signal_in_text_gives_empty_list(tmp_db):
    agenda = ResearchAgenda(
        hypotheses=["Generic macro hypothesis with no signal names"],
        project="p", universe="u", market="US",
    )
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert tasks[0].suggested_signals == []


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

def test_commander_tasks_ordered_by_priority_descending(tmp_db, agenda):
    tasks = Commander().run(agenda, db_path=tmp_db)
    priorities = [t.priority for t in tasks]
    assert priorities == sorted(priorities, reverse=True)


# ---------------------------------------------------------------------------
# Duplicate filtering
# ---------------------------------------------------------------------------

def test_commander_skips_already_run_hypothesis(tmp_db):
    upsert_experiment({
        "experiment_id": "exp_001_test",
        "project": "project_test",
        "universe": "test_universe",
        "hypothesis": "mr_ret_5 mean-reversion works on short horizons",
    }, db_path=tmp_db)

    agenda = ResearchAgenda(
        hypotheses=["mr_ret_5 mean-reversion works on short horizons"],
        project="project_test",
        universe="test_universe",
        market="US",
    )
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert len(tasks) == 0


def test_commander_keeps_new_hypothesis_when_one_is_duplicate(tmp_db):
    upsert_experiment({
        "experiment_id": "exp_001_test",
        "project": "project_test",
        "universe": "test_universe",
        "hypothesis": "mr_ret_5 mean-reversion works on short horizons",
    }, db_path=tmp_db)

    agenda = ResearchAgenda(
        hypotheses=[
            "mr_ret_5 mean-reversion works on short horizons",
            "low_vol_20 captures low-volatility premium",
        ],
        project="project_test",
        universe="test_universe",
        market="US",
    )
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert len(tasks) == 1
    assert "low_vol_20" in tasks[0].hypothesis


def test_commander_dedup_is_case_insensitive(tmp_db):
    upsert_experiment({
        "experiment_id": "exp_001_test",
        "project": "project_test",
        "universe": "test_universe",
        "hypothesis": "MR_RET_5 MEAN-REVERSION WORKS",
    }, db_path=tmp_db)

    agenda = ResearchAgenda(
        hypotheses=["mr_ret_5 mean-reversion works"],
        project="project_test",
        universe="test_universe",
        market="US",
    )
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert len(tasks) == 0


def test_commander_dedup_only_filters_same_project_universe(tmp_db):
    upsert_experiment({
        "experiment_id": "exp_001_other",
        "project": "other_project",
        "universe": "other_universe",
        "hypothesis": "mr_ret_5 mean-reversion works",
    }, db_path=tmp_db)

    agenda = ResearchAgenda(
        hypotheses=["mr_ret_5 mean-reversion works"],
        project="project_test",
        universe="test_universe",
        market="US",
    )
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert len(tasks) == 1


def test_commander_empty_agenda_returns_empty(tmp_db):
    agenda = ResearchAgenda(hypotheses=[], project="p", universe="u", market="US")
    tasks = Commander().run(agenda, db_path=tmp_db)
    assert tasks == []
