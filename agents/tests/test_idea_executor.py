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

from agents.protocol import ProposedIdea, LedgerUpdate
from agents.storage.db import create_all_tables, get_connection
from agents.storage.conversation_store import get_messages_by_type
from agents.storage.ledger_store import get_experiment
from agents.storage.lessons_store import get_lessons_for_experiment
from agents.idea_generator import approval_queue as q
from agents.idea_generator import idea_executor
from agents.idea_generator import scoring
from agents.ledger_agent.ledger_agent import LedgerAgent


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
# Milestone 9: SignalLibrarian post-ledger hook (isolated)
# ---------------------------------------------------------------------------

def test_librarian_hook_records_context(db, completed_dir, data_root):
    from agents.storage import context_store as cs
    idea_id = _approve_idea(db)
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    assert res.outcome == "executed"
    # The librarian should have decomposed the experiment into context cells.
    obs = cs.list_observations(db_path=db)
    assert any(o["experiment_id"] == res.experiment_id for o in obs)


def test_librarian_failure_does_not_break_execution(db, completed_dir, data_root):
    class _BoomLibrarian:
        def record_experiment(self, *a, **k):
            raise RuntimeError("boom")

    idea_id = _approve_idea(db)
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db, librarian=_BoomLibrarian(),
    )
    # A librarian failure must never roll back a ledgered execution.
    assert res.outcome == "executed"
    assert get_experiment(res.experiment_id, db_path=db) is not None


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


# ---------------------------------------------------------------------------
# M7.1 — R1: ledger-success gating + recovery
# ---------------------------------------------------------------------------

class _FailingLedger(LedgerAgent):
    """Simulates a ledger persistence failure: writes nothing, reports not-ok."""
    def run(self, result, critique, db_path=None):
        return LedgerUpdate(
            experiment_id=result.experiment_id,
            decision=critique.decision,
            conclusion="(simulated failure)",
            lesson_written=False,
            source_idea_id=critique.source_idea_id,
            status_written=False,
        )


def test_ledger_failure_leaves_idea_executing(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, ledger=_FailingLedger(), db_path=db,
    )
    assert res.outcome == "error"
    assert "ledger_write_failed" in res.reasons
    # Idea is recoverable, NOT executed.
    assert q.get_idea(idea_id, db_path=db)["status"] == "executing"
    # No lesson was persisted (the whole point of the gate).
    assert get_lessons_for_experiment(res.experiment_id, db_path=db) == []


def test_ledger_failure_still_stamps_provenance(db, completed_dir, data_root):
    # R3: provenance is stamped BEFORE the ledger runs, so even a failed ledger
    # leaves a fully-attributable experiment row (no orphan).
    idea_id = _approve_idea(db, source_model="claude-sonnet-4")
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, ledger=_FailingLedger(), db_path=db,
    )
    row = get_experiment(res.experiment_id, db_path=db)
    assert row["source_idea_id"] == idea_id
    assert row["source_model"] == "claude-sonnet-4"


def test_ledger_failure_logs_incomplete_event(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, ledger=_FailingLedger(), db_path=db,
    )
    msgs = get_messages_by_type("cycle_x", "idea_execution_incomplete", db_path=db)
    assert len(msgs) == 1
    assert msgs[0]["payload"]["recoverable"] is True


def test_recover_completes_stuck_idea(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    # First attempt fails at the ledger.
    idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, ledger=_FailingLedger(), db_path=db,
    )
    exp_before = q.get_idea(idea_id, db_path=db)["experiment_id"]

    # Recovery with a real ledger: no new experiment, idea completes.
    out = idea_executor.recover_incomplete_executions(
        completed_dir=completed_dir, db_path=db,
    )
    assert len(out.recovered) == 1
    assert out.still_incomplete == []

    idea = q.get_idea(idea_id, db_path=db)
    assert idea["status"] == "executed"
    assert idea["experiment_id"] == exp_before  # NOT a duplicate experiment
    assert len(get_lessons_for_experiment(exp_before, db_path=db)) == 1
    # Exactly one experiment row total — recovery did not re-run the pipeline.
    with get_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    assert n == 1


def test_recover_is_noop_when_nothing_stuck(db, completed_dir, data_root):
    out = idea_executor.recover_incomplete_executions(
        completed_dir=completed_dir, db_path=db)
    assert out.recovered == []
    assert out.still_incomplete == []


# ---------------------------------------------------------------------------
# M7.1 — R2: atomic claim prevents double execution
# ---------------------------------------------------------------------------

def test_already_claimed_idea_is_not_re_executed(db, completed_dir, data_root):
    idea_id = _approve_idea(db)
    # Simulate a concurrent executor having already claimed the idea.
    assert q.claim_for_execution(idea_id, db_path=db) is True
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    # get_approved no longer sees it (status='executing') -> no second run.
    assert res.outcome == "rejected"
    assert "not_approved" in res.reasons
    with get_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    assert n == 0
