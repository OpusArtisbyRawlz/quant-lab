"""Tests for the Milestone 10 PR-7 ResearchLoop.

Proves the PR-7 requirements:
  * a tick is deterministic, resumable, reconstructible from storage, idempotent;
  * the loop preserves the human approval gate (it never auto-approves and never
    executes an unapproved idea);
  * the loop preserves the M7 execution path and the M9 learning path (it
    delegates to the unchanged executor, which runs the librarian);
  * recovery works for: crash before dispatch, crash after dispatch, crash after
    ledger write, and a cold restart reconciliation.

All execution uses a synthetic data_dict_provider, so nothing touches the
network or the real data root.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.protocol import ProposedIdea
from agents.storage.db import create_all_tables, get_connection
from agents.storage import loop_store, scheduler_store, ledger_store
from agents.idea_generator import approval_queue as q
from agents.idea_generator import idea_executor, scoring
from agents.campaign_manager import CampaignManager
from agents.research_strategist import ResearchStrategist
from agents.research_loop import ResearchLoop, LoopConfig


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "loop.db"
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


def _campaign(db, cid="camp", *, budget=0):
    mgr = CampaignManager(db)
    mgr.create_campaign(cid, "theme", goal_spec={"priority": 0.5},
                        budget_experiments=budget)
    mgr.activate(cid)
    return cid


def _seed_and_approve(db, cid, *, signals=("mr_ret_5",),
                      hypothesis="Short reversal works",
                      market="us", universe="test_universe"):
    """Seed the campaign root as a pending idea, then simulate the HUMAN
    approving it. Returns the idea_id."""
    strat = ResearchStrategist(db_path=db)
    res = strat.seed(cid, hypothesis, signals=list(signals),
                     market=market, universe=universe)
    assert q.get_idea(res.idea_id, db_path=db)["status"] == "pending"
    assert q.approve_idea(res.idea_id, db_path=db) is True
    return res.idea_id


def _loop(db, completed_dir, data_root, **cfg):
    return ResearchLoop(
        db, config=LoopConfig(**cfg),
        data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider,
    )


# ---------------------------------------------------------------------------
# Human approval gate is preserved
# ---------------------------------------------------------------------------

def test_unapproved_ideas_are_never_dispatched(db, completed_dir, data_root):
    cid = _campaign(db)
    strat = ResearchStrategist(db_path=db)
    res = strat.seed(cid, "h", signals=["mr_ret_5"], market="us",
                     universe="test_universe")
    # The seed idea is pending — NOT approved. Run a full tick.
    loop = _loop(db, completed_dir, data_root)
    report = loop.run_tick(cid)

    assert q.get_idea(res.idea_id, db_path=db)["status"] == "pending"
    # Nothing scheduled or executed without approval.
    assert report.phase("schedule").evidence["scheduled"] == 0
    assert report.phase("dispatch").evidence["executed"] == []
    assert scheduler_store.list_events(db_path=db) == []


def test_loop_never_auto_approves(db, completed_dir, data_root):
    cid = _campaign(db)
    strat = ResearchStrategist(db_path=db)
    strat.seed(cid, "h", signals=["mr_ret_5"], market="us",
               universe="test_universe")
    _loop(db, completed_dir, data_root).run_tick(cid)
    # No idea is in 'approved'/'executed' purely from the loop running.
    assert q.list_approved(db_path=db) == []
    assert q.list_by_status("executed", db_path=db) == []


# ---------------------------------------------------------------------------
# Full happy-path tick: approved idea is executed via the M7 path
# ---------------------------------------------------------------------------

def test_approved_idea_executes_and_tick_completes(db, completed_dir, data_root):
    cid = _campaign(db)
    idea_id = _seed_and_approve(db, cid)
    report = _loop(db, completed_dir, data_root).run_tick(cid)

    assert loop_store.tick_completed(report.tick_id, db_path=db)
    assert report.phase("dispatch").evidence["executed"] == [idea_id]
    # Idea progressed approved -> executed via the unchanged executor.
    assert q.get_idea(idea_id, db_path=db)["status"] == "executed"
    # Exactly one experiment was produced and recorded in the ledger.
    assert len(ledger_store.list_experiments(db_path=db)) == 1
    # Scheduler logged dispatch + success.
    actions = [e["action"] for e in scheduler_store.list_events(idea_id=idea_id, db_path=db)]
    assert scheduler_store.ACTION_DISPATCHED in actions
    assert scheduler_store.ACTION_SUCCEEDED in actions


# ---------------------------------------------------------------------------
# Determinism + reconstructible-from-storage
# ---------------------------------------------------------------------------

def test_tick_ids_are_deterministic_and_sequential(db, completed_dir, data_root):
    cid = _campaign(db)
    _seed_and_approve(db, cid)
    loop = _loop(db, completed_dir, data_root)
    r1 = loop.run_tick(cid)
    r2 = loop.run_tick(cid)
    assert r1.tick_id == f"{cid}#t0001"
    assert r2.tick_id == f"{cid}#t0002"        # next sequential tick
    assert r1.resumed is False and r2.resumed is False
    # The whole tick history is reconstructible from the checkpoint log alone.
    assert loop_store.distinct_tick_ids(db_path=db) == [r1.tick_id, r2.tick_id]


def test_completed_tick_is_not_recomputed_on_resume(db, completed_dir, data_root):
    cid = _campaign(db)
    _seed_and_approve(db, cid)
    loop = _loop(db, completed_dir, data_root)
    loop.run_tick(cid)
    n_exp = len(ledger_store.list_experiments(db_path=db))
    n_ckpt = len(loop_store.list_checkpoints(db_path=db))
    # Running the SAME completed tick id again is a no-op (it is completed, so a
    # fresh run_tick rolls to the next tick which has nothing approved to do).
    loop.run_tick(cid)
    assert len(ledger_store.list_experiments(db_path=db)) == n_exp   # no dup
    assert len(loop_store.list_checkpoints(db_path=db)) > n_ckpt      # new tick logged


# ---------------------------------------------------------------------------
# Recovery: crash BEFORE dispatch
# ---------------------------------------------------------------------------

def test_recovery_crash_before_dispatch(db, completed_dir, data_root, monkeypatch):
    cid = _campaign(db)
    idea_id = _seed_and_approve(db, cid)
    loop = _loop(db, completed_dir, data_root)

    # Make the dispatch phase crash AFTER schedule has committed its events.
    def _boom(*a, **k):
        raise RuntimeError("crash before execution")
    monkeypatch.setattr(idea_executor, "run_single_approved_idea", _boom)
    with pytest.raises(RuntimeError):
        loop.run_tick(cid)

    # schedule completed (idea is in-flight); dispatch did NOT complete.
    tick_id = f"{cid}#t0001"
    assert loop_store.phase_completed(tick_id, loop_store.PHASE_SCHEDULE, db_path=db)
    assert not loop_store.phase_completed(tick_id, loop_store.PHASE_DISPATCH, db_path=db)
    assert idea_id in scheduler_store.in_flight_idea_ids(db_path=db)

    # Restart: restore the executor and resume. The SAME tick resumes, generate
    # and schedule are skipped (no duplicate ideas / dispatches), dispatch runs.
    monkeypatch.undo()
    report = loop.run_tick(cid)
    assert report.resumed is True and report.tick_id == tick_id
    assert report.phase("schedule").ran is False        # skipped
    assert report.phase("dispatch").ran is True
    assert q.get_idea(idea_id, db_path=db)["status"] == "executed"
    assert len(ledger_store.list_experiments(db_path=db)) == 1


# ---------------------------------------------------------------------------
# Recovery: crash AFTER dispatch (idempotent — no double execution)
# ---------------------------------------------------------------------------

def test_recovery_crash_after_dispatch_is_idempotent(db, completed_dir, data_root, monkeypatch):
    cid = _campaign(db)
    idea_id = _seed_and_approve(db, cid)
    loop = _loop(db, completed_dir, data_root)

    # Let dispatch finish executing, then crash in the LEARN phase (patch the
    # instance's learn step so recover's own reconcile is unaffected).
    real_learn = loop._do_learn

    def _boom(tick_id, campaign_id):
        raise RuntimeError("crash after dispatch")
    loop._do_learn = _boom
    with pytest.raises(RuntimeError):
        loop.run_tick(cid)

    tick_id = f"{cid}#t0001"
    assert loop_store.phase_completed(tick_id, loop_store.PHASE_DISPATCH, db_path=db)
    assert q.get_idea(idea_id, db_path=db)["status"] == "executed"
    assert len(ledger_store.list_experiments(db_path=db)) == 1

    # Restart: resume. Dispatch is skipped (already completed), so the idea is
    # NOT executed a second time.
    loop._do_learn = real_learn
    report = loop.run_tick(cid)
    assert report.resumed is True
    assert report.phase("dispatch").ran is False         # not re-executed
    assert loop_store.tick_completed(tick_id, db_path=db)
    assert len(ledger_store.list_experiments(db_path=db)) == 1   # still one


# ---------------------------------------------------------------------------
# Recovery: crash AFTER ledger write (executor R1 recovery via recover phase)
# ---------------------------------------------------------------------------

def test_recovery_crash_after_ledger_write(db, completed_dir, data_root):
    cid = _campaign(db)
    idea_id = _seed_and_approve(db, cid)

    # Run a real execution to create the experiment + artifacts + lesson.
    res = idea_executor.run_single_approved_idea(
        idea_id, data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider, db_path=db,
    )
    assert res.outcome == "executed"
    exp_id = res.experiment_id
    n_exp = len(ledger_store.list_experiments(db_path=db))

    # Simulate a crash in the window AFTER the ledger write but BEFORE
    # mark_executed: the idea is stuck in 'executing' with its experiment linked.
    with get_connection(db) as conn:
        conn.execute(
            "UPDATE pending_ideas SET status='executing' WHERE idea_id=?",
            (idea_id,))
        conn.commit()

    # The loop's recover phase repairs it WITHOUT creating a duplicate experiment.
    report = _loop(db, completed_dir, data_root).run_tick(cid)
    assert report.phase("recover").evidence["recovered_executions"] == 1
    assert q.get_idea(idea_id, db_path=db)["status"] == "executed"
    assert q.get_idea(idea_id, db_path=db)["experiment_id"] == exp_id
    assert len(ledger_store.list_experiments(db_path=db)) == n_exp   # no dup


# ---------------------------------------------------------------------------
# Recovery: cold restart reconciliation
# ---------------------------------------------------------------------------

def test_restart_reconciliation_resolves_orphan_dispatch(db, completed_dir, data_root):
    cid = _campaign(db)
    idea_id = _seed_and_approve(db, cid)

    # Simulate an interrupted run from a previous process: the scheduler recorded
    # a dispatch but the result was never recorded (idea still approved).
    from agents.research_scheduler import ResearchScheduler
    ResearchScheduler(db).dispatch()
    assert idea_id in scheduler_store.in_flight_idea_ids(db_path=db)

    # A cold restart: a brand-new loop's recover phase reconciles the orphan from
    # ground-truth state (still approved -> failed/interrupted -> retry-eligible).
    loop = _loop(db, completed_dir, data_root)
    report = loop.run_tick(cid)
    recover_ev = report.phase("recover").evidence
    assert recover_ev["scheduler_resolved_failed"] >= 1
    # The orphan was resolved (it is no longer the unresolved dispatch from before
    # this tick's own scheduling); the idea was re-dispatched and executed.
    assert q.get_idea(idea_id, db_path=db)["status"] == "executed"
    assert loop_store.tick_completed(report.tick_id, db_path=db)


# ---------------------------------------------------------------------------
# Budget: the loop respects the scheduler's campaign budget
# ---------------------------------------------------------------------------

def test_loop_respects_campaign_budget(db, completed_dir, data_root):
    cid = _campaign(db, budget=1)
    # Two approved ideas in the campaign; budget allows only one experiment.
    id1 = _seed_and_approve(db, cid)
    # A second approved idea, same campaign.
    idea = ProposedIdea(hypothesis="another", suggested_signals=("mr_ret_5",),
                        source_model="t", scores=scoring.compute_scores(
                            "another", ("mr_ret_5",)),
                        market="us", universe="test_universe")
    id2 = q.make_idea_id(idea, db_path=db)
    q.enqueue(idea, id2, db_path=db)
    q.approve_idea(id2, db_path=db)
    from agents.storage import campaign_store
    campaign_store.link_idea_to_campaign(id2, cid, db_path=db)

    report = _loop(db, completed_dir, data_root, generate=False).run_tick(cid)
    # Budget 1 ⇒ only one scheduled this tick.
    assert report.phase("schedule").evidence["scheduled"] == 1
    assert len(ledger_store.list_experiments(db_path=db)) == 1
