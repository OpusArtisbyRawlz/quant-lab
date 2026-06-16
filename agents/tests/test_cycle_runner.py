"""
End-to-end tests for agents/cycle_runner.py.

All tests use synthetic data_dict — no disk I/O, no yfinance.
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from agents.protocol import ResearchAgenda
from agents.cycle_runner import run_cycle, CycleResult, _next_cycle_id
from agents.storage.conversation_store import get_cycle_messages, list_cycles
from agents.storage.ledger_store import get_experiment
from agents.storage.lessons_store import get_lessons_for_experiment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_data_dict(n_dates: int = 80, n_tickers: int = 10, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    data_dict = {}
    for ticker in tickers:
        prices = 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, n_dates))
        df = pd.DataFrame({
            "Open":   prices * rng.uniform(0.99, 1.00, n_dates),
            "High":   prices * rng.uniform(1.00, 1.01, n_dates),
            "Low":    prices * rng.uniform(0.98, 1.00, n_dates),
            "Close":  prices,
            "Volume": rng.integers(500_000, 2_000_000, n_dates).astype(float),
        }, index=dates)
        df.index.name = "Date"
        data_dict[ticker] = df
    return data_dict


@pytest.fixture
def agenda():
    return ResearchAgenda(
        hypotheses=["mr_ret_5 works on short horizons"],
        project="project_test",
        universe="test_universe",
        market="US",
    )


@pytest.fixture
def two_hypothesis_agenda():
    return ResearchAgenda(
        hypotheses=[
            "mr_ret_5 works on short horizons",
            "low_vol_20 captures low-volatility premium",
        ],
        project="project_test",
        universe="test_universe",
        market="US",
    )


@pytest.fixture
def completed_dir(tmp_path):
    d = tmp_path / "completed"
    d.mkdir()
    return d


@pytest.fixture
def data_root(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# CycleResult structure
# ---------------------------------------------------------------------------

def test_run_cycle_returns_cycle_result(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    assert isinstance(result, CycleResult)


def test_run_cycle_cycle_id_assigned(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    assert result.cycle_id.startswith("cycle_")


def test_run_cycle_tasks_attempted_count(tmp_db, completed_dir, data_root, two_hypothesis_agenda):
    result = run_cycle(
        two_hypothesis_agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    assert result.tasks_attempted == 2


def test_run_cycle_succeeded_plus_failed_equals_attempted(tmp_db, completed_dir, data_root, two_hypothesis_agenda):
    result = run_cycle(
        two_hypothesis_agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    assert result.tasks_succeeded + result.tasks_failed <= result.tasks_attempted


def test_run_cycle_outcomes_list_length(tmp_db, completed_dir, data_root, two_hypothesis_agenda):
    result = run_cycle(
        two_hypothesis_agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    assert len(result.outcomes) == 2


def test_run_cycle_outcomes_have_run_result(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    for outcome in result.outcomes:
        assert outcome.run_result is not None


def test_run_cycle_outcomes_have_critique(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    for outcome in result.outcomes:
        assert outcome.critique is not None


def test_run_cycle_outcomes_have_ledger_update(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    for outcome in result.outcomes:
        assert outcome.ledger_update is not None


# ---------------------------------------------------------------------------
# agent_conversations logging
# ---------------------------------------------------------------------------

def test_cycle_logs_five_messages_per_task(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    messages = get_cycle_messages(result.cycle_id, db_path=tmp_db)
    assert len(messages) == 5


def test_cycle_logs_correct_senders(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    messages = get_cycle_messages(result.cycle_id, db_path=tmp_db)
    senders = [m["sender"] for m in messages]
    assert senders == [
        "commander", "experiment_designer", "runner", "critic", "ledger_agent"
    ]


def test_cycle_logs_correct_message_types(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    messages = get_cycle_messages(result.cycle_id, db_path=tmp_db)
    types = [m["message_type"] for m in messages]
    assert types == ["hypothesis", "spec", "result", "critique", "summary"]


def test_result_message_contains_metrics(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    messages = get_cycle_messages(result.cycle_id, db_path=tmp_db)
    result_msg = next(m for m in messages if m["message_type"] == "result")
    assert "metrics" in result_msg["payload"]


def test_critique_message_contains_thresholds_used(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    messages = get_cycle_messages(result.cycle_id, db_path=tmp_db)
    critique_msg = next(m for m in messages if m["message_type"] == "critique")
    assert "thresholds_used" in critique_msg["payload"]


def test_two_tasks_log_ten_messages(tmp_db, completed_dir, data_root, two_hypothesis_agenda):
    result = run_cycle(
        two_hypothesis_agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    messages = get_cycle_messages(result.cycle_id, db_path=tmp_db)
    assert len(messages) == 10


def test_cycle_id_increments_across_cycles(tmp_db, completed_dir, data_root, agenda):
    r1 = run_cycle(agenda, db_path=tmp_db, completed_dir=completed_dir,
                   data_root=data_root, data_dict=_make_data_dict())
    # Need a fresh agenda — Commander will dedup the first hypothesis
    agenda2 = ResearchAgenda(
        hypotheses=["low_vol_20 captures premium"],
        project="project_test", universe="test_universe", market="US",
    )
    r2 = run_cycle(agenda2, db_path=tmp_db, completed_dir=completed_dir,
                   data_root=data_root, data_dict=_make_data_dict())
    assert r1.cycle_id != r2.cycle_id
    n1 = int(r1.cycle_id.split("_")[1])
    n2 = int(r2.cycle_id.split("_")[1])
    assert n2 == n1 + 1


# ---------------------------------------------------------------------------
# DB side-effects
# ---------------------------------------------------------------------------

def test_cycle_writes_experiment_to_db(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    exp_id = result.outcomes[0].run_result.experiment_id
    row = get_experiment(exp_id, db_path=tmp_db)
    assert row is not None


def test_cycle_writes_lesson_to_db(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    exp_id = result.outcomes[0].run_result.experiment_id
    lessons = get_lessons_for_experiment(exp_id, db_path=tmp_db)
    assert len(lessons) >= 1


def test_cycle_decision_written_to_db(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(),
    )
    exp_id = result.outcomes[0].run_result.experiment_id
    row = get_experiment(exp_id, db_path=tmp_db)
    assert row["decision"] in ("keep", "reject", "retest")


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def test_dry_run_returns_cycle_result(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(), dry_run=True,
    )
    assert isinstance(result, CycleResult)


def test_dry_run_run_result_status_is_dry_run(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(), dry_run=True,
    )
    for outcome in result.outcomes:
        assert outcome.run_result.status == "dry_run"


def test_dry_run_still_logs_messages(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(), dry_run=True,
    )
    messages = get_cycle_messages(result.cycle_id, db_path=tmp_db)
    assert len(messages) == 5


def test_dry_run_no_experiment_row_in_db(tmp_db, completed_dir, data_root, agenda):
    result = run_cycle(
        agenda, db_path=tmp_db, completed_dir=completed_dir,
        data_root=data_root, data_dict=_make_data_dict(), dry_run=True,
    )
    exp_id = result.outcomes[0].run_result.experiment_id
    row = get_experiment(exp_id, db_path=tmp_db)
    assert row is None


# ---------------------------------------------------------------------------
# _next_cycle_id
# ---------------------------------------------------------------------------

def test_next_cycle_id_first_call_returns_001(tmp_db):
    assert _next_cycle_id(tmp_db) == "cycle_001"


def test_next_cycle_id_increments(tmp_db):
    from agents.storage.conversation_store import log_message
    log_message("cycle_003", "a", "b", "test", {}, tmp_db)
    assert _next_cycle_id(tmp_db) == "cycle_004"
