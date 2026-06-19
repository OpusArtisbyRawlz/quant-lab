"""
Tests for idea_generator/idea_executor.py — the M7 bridge.

Covers the full path: approved idea -> spec -> M5 runner -> Critic -> Ledger,
plus provenance stamping, status transition, idempotency, exec-time validation
rejection with reason codes, and the no-auto-execution invariant.

All runs use synthetic DataFrames via a data_dict_provider, so nothing touches
the network, yfinance, or the real data root.
"""

import numpy as np
import pandas as pd
import pytest

from agents.protocol import ProposedIdea
from agents.storage.db import create_all_tables, get_connection
from agents.storage.conversation_store import get_messages_by_type
from agents.storage.ledger_store import get_experiment
from agents.storage.lessons_store import get_lessons_for_experiment
from agents.idea_generator import approval_queue as q
from agents.idea_generator import idea_executor
from agents.idea_generator import scoring


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "exec.db"
    create_all_tables(path)
    return path


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


def _make_data_dict(n_dates=80, n_tickers=10, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    out = {}
    for i in range(n_tickers):
        prices = 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, n_dates))
        df = pd.DataFrame({
            "Open": prices * rng.uniform(0.99, 1.00, n_dates),
            "High": prices * rng.uniform(1.00, 1.01, n_dates),
            "Low": prices * rng.uniform(0.98, 1.00, n_dates),
            "Close": prices,
            "Volume": rng.integers(500_000, 2_000_000, n_dates).astype(float),
        }, index=dates)
        df.index.name = "Date"
        out[f"T{i:02d}"] = df
    return out


def _provider(spec):
    return _make_data_dict()


def _approve_idea(db, *, signals=("mr_ret_5",), hypothesis="Short reversal works",
                  market="us", universe="test_universe", source_model="fake-idea-llm"):
    """Enqueue a validated idea and approve it. Returns idea_id."""
    idea = ProposedIdea(
        hypothesis=hypothesis,
        suggested_signals=tuple(signals),
        source_model=source_model,
        scores=scoring.compute_scores(hypothesis, tuple(signals)),
        market=market,
        universe=universe,
    )
    idea_id = q.make_idea_id(idea, db_path=db)
    q.enqueue(idea, idea_id, cycle_id="cycle_x", db_path=db)
    assert q.approve_idea(idea_id, db_path=db) is True
    return idea_id


# ---------------------------------------------------------------------------
# Happy path: approved idea -> experiment -> critique -> ledger
# ---------------------------------------------------------------------------

def test_single_approved_idea_executes(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    assert res.outcome == "executed"
    assert res.experiment_id is not None
    assert res.decision in ("keep", "reject", "retest")


def test_experiment_row_carries_provenance(db, completed_dir, data_root):
    idea_id = _approve_idea(db, source_model="fake-idea-llm")
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    row = get_experiment(res.experiment_id, db_path=db)
    assert row["source_idea_id"] == idea_id
    assert row["source_model"] == "fake-idea-llm"


def test_idea_marked_executed_and_linked(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    idea = q.get_idea(idea_id, db_path=db)
    assert idea["status"] == "executed"
    assert idea["experiment_id"] == res.experiment_id


def test_net_metrics_and_robustness_present(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    msgs = get_messages_by_type("cycle_x", "idea_executed", db_path=db)
    assert len(msgs) == 1
    payload = msgs[0]["payload"]
    assert payload["net_sharpe"] is not None
    assert "robustness_flags" in payload


def test_lesson_written_for_executed_idea(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    lessons = get_lessons_for_experiment(res.experiment_id, db_path=db)
    assert len(lessons) >= 1


# ---------------------------------------------------------------------------
# Idempotency / resumability
# ---------------------------------------------------------------------------

def test_rerun_does_not_double_process(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    # Second run: idea is no longer 'approved' -> not_approved rejection.
    res2 = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    assert res2.outcome == "rejected"
    assert "not_approved" in res2.reasons


def test_not_approved_idea_has_no_side_effects(db, completed_dir, data_root):
    res = idea_executor.run_single_approved_idea(
        "idea_999_nonexistent", data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    assert res.outcome == "rejected"
    with get_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    assert n == 0


# ---------------------------------------------------------------------------
# Execution-time validation failure -> reject with reason code
# ---------------------------------------------------------------------------

def test_unknown_signal_rejected_with_reason(db, completed_dir, data_root):
    idea_id = _approve_idea(db, signals=("totally_made_up",))
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    assert res.outcome == "rejected"
    assert "signal_unavailable" in res.reasons
    # No experiment row, idea transitioned to rejected.
    with get_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    assert n == 0
    assert q.get_idea(idea_id, db_path=db)["status"] == "rejected"


def test_exec_rejection_logged_with_stage(db, completed_dir, data_root):
    idea_id = _approve_idea(db, signals=("totally_made_up",))
    idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    msgs = get_messages_by_type("cycle_x", "idea_rejected", db_path=db)
    assert any(m["payload"].get("stage") == "execution_validation" for m in msgs)


def test_missing_universe_data_rejected(db, completed_dir, data_root):
    # No data_dict_provider -> real data check against empty data_root.
    idea_id = _approve_idea(db, universe="no_such_universe")
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=None, db_path=db,
    )
    assert res.outcome == "rejected"
    assert "universe_data_missing" in res.reasons


# ---------------------------------------------------------------------------
# Batch drain
# ---------------------------------------------------------------------------

def test_run_approved_ideas_drains_all(db, completed_dir, data_root):
    _approve_idea(db, hypothesis="Idea one", signals=("mr_ret_5",))
    _approve_idea(db, hypothesis="Idea two", signals=("low_vol_20",))
    batch = idea_executor.run_approved_ideas(
        data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    assert len(batch.executed) == 2
    assert batch.rejected == []
    assert q.list_approved(db_path=db) == []


def test_run_approved_ideas_respects_limit(db, completed_dir, data_root):
    _approve_idea(db, hypothesis="Idea one", signals=("mr_ret_5",))
    _approve_idea(db, hypothesis="Idea two", signals=("low_vol_20",))
    batch = idea_executor.run_approved_ideas(
        data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, limit=1, db_path=db,
    )
    assert len(batch.executed) == 1
    assert len(q.list_approved(db_path=db)) == 1  # one still approved


# ---------------------------------------------------------------------------
# No-auto-execution invariant: approval alone never executes
# ---------------------------------------------------------------------------

def test_approval_alone_executes_nothing(db, completed_dir, data_root):
    _approve_idea(db)
    # We only approved — never called the executor.
    with get_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    assert n == 0
    assert len(q.list_approved(db_path=db)) == 1
