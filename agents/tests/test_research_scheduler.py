"""Tests for the Milestone 10 PR-6 ResearchScheduler.

Proves the PR-6 requirements:
  * deterministic dispatch order (identical state ⇒ identical plan);
  * per-campaign and global budget limits are enforced;
  * retries behave correctly (failed ideas re-dispatched within the allowance,
    exhausted past it);
  * startup reconciliation works (campaign projections reconciled);
  * interrupted runs recover correctly (orphan dispatches resolved from
    ground-truth stored state, interrupted ones become retry-eligible);
  * no idea executes without approval (the scheduler only ever reads the
    approved pool and writes to the scheduler_event log — it never claims,
    specs, or executes).

The scheduler is a planning/ordering layer: these tests assert on the
append-only scheduler_event log and the returned plans, never on execution.
"""

from __future__ import annotations

import json

import pytest

from agents.storage import (
    scheduler_store, campaign_store, ledger_store, context_store,
)
from agents.storage.db import get_connection
from agents.idea_generator import approval_queue
from agents.campaign_manager.manager import CampaignManager
from agents.research_scheduler import (
    ResearchScheduler,
    SchedulerConfig,
    DispatchItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approved(db, idea_id, *, signals=("mom",), market="India",
              universe="NIFTY50", bar_type="time", campaign_id=None,
              status="approved", experiment_id=None):
    """Insert a pending_ideas row directly in the given status (default
    'approved' = human gate already cleared)."""
    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO pending_ideas
                (idea_id, hypothesis, suggested_signals, source_model,
                 market, universe, bar_type, metadata, status, validation_ok,
                 validation_reasons, experiment_id, campaign_id, created_at)
            VALUES (?, ?, ?, 'test', ?, ?, ?, '{}', ?, 1, '[]', ?, ?, ?)
            """,
            (idea_id, f"hyp {idea_id}", json.dumps(list(signals)),
             market, universe, bar_type, status, experiment_id, campaign_id,
             f"2026-01-01T00:00:{int(idea_id[-1]) if idea_id[-1].isdigit() else 0:02d}"),
        )
        conn.commit()
    return idea_id


def _campaign(db, cid, *, priority=0.0, budget=0, activate=True):
    mgr = CampaignManager(db)
    mgr.create_campaign(cid, "t", goal_spec={"priority": priority},
                        budget_experiments=budget)
    if activate:
        mgr.activate(cid)
    return cid


def _produce_experiment(db, idea_id, eid):
    """Simulate M7 finishing an idea: create the experiment row and link it on
    the idea (mark executed), so campaign budget accounting sees it."""
    ledger_store.upsert_experiment(
        {"experiment_id": eid, "hypothesis": "h", "status": "completed",
         "bar_type": "time"},
        db_path=db,
    )
    with get_connection(db) as conn:
        conn.execute(
            "UPDATE pending_ideas SET status='executed', experiment_id=? "
            "WHERE idea_id=?",
            (eid, idea_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Deterministic dispatch order
# ---------------------------------------------------------------------------

def test_dispatch_order_is_deterministic(tmp_db):
    db = tmp_db
    _campaign(db, "c_hi", priority=0.9)
    _campaign(db, "c_lo", priority=0.1)
    # Distinct signals ⇒ distinct M9 context keys, so the PR-8 context-diversity
    # safeguard never trims them; this test isolates campaign/rank ordering.
    _approved(db, "i1", signals=("mom",), campaign_id="c_lo")
    _approved(db, "i2", signals=("rev",), campaign_id="c_hi")
    _approved(db, "i3", signals=("vol",), campaign_id=None)  # ad-hoc

    s = ResearchScheduler(db)
    plan1 = [d.idea_id for d in s.experiment_queue()]
    plan2 = [d.idea_id for d in s.experiment_queue()]
    assert plan1 == plan2                      # pure function of state
    # High-priority campaign ideas come before low-priority; ad-hoc last.
    assert plan1.index("i2") < plan1.index("i1")
    assert plan1.index("i1") < plan1.index("i3")


def test_only_approved_ideas_are_planned(tmp_db):
    db = tmp_db
    _approved(db, "ap1", status="approved")
    _approved(db, "pe1", status="pending")
    _approved(db, "ex1", status="executing")
    _approved(db, "ed1", status="executed")
    _approved(db, "rj1", status="rejected")

    s = ResearchScheduler(db)
    ids = [d.idea_id for d in s.experiment_queue()]
    assert ids == ["ap1"]


# ---------------------------------------------------------------------------
# No execution without approval
# ---------------------------------------------------------------------------

def test_dispatch_never_executes_or_claims(tmp_db):
    db = tmp_db
    _approved(db, "i1")
    s = ResearchScheduler(db)
    plan = s.dispatch()

    # The idea remains 'approved' — the scheduler did NOT claim/execute it.
    assert approval_queue.get_idea("i1", db_path=db)["status"] == "approved"
    # Exactly one dispatched event was recorded.
    evs = scheduler_store.list_events(idea_id="i1", db_path=db)
    assert [e["action"] for e in evs] == [scheduler_store.ACTION_DISPATCHED]
    assert plan[0].attempt == 1


def test_in_flight_ideas_not_redispatched(tmp_db):
    db = tmp_db
    _approved(db, "i1")
    s = ResearchScheduler(db)
    s.dispatch()                       # i1 now in-flight (open dispatch)
    # A second dispatch must not re-plan the in-flight idea.
    assert s.experiment_queue() == []


# ---------------------------------------------------------------------------
# Budget limits
# ---------------------------------------------------------------------------

def test_per_campaign_budget_enforced(tmp_db):
    db = tmp_db
    _campaign(db, "c", priority=0.5, budget=2)
    for n in range(4):
        _approved(db, f"i{n}", campaign_id="c")

    s = ResearchScheduler(db)
    plan = s.experiment_queue()
    assert len(plan) == 2              # only budget-many planned
    assert s.remaining_budget("c") == 2


def test_global_dispatch_limit_enforced(tmp_db):
    db = tmp_db
    # Distinct signals ⇒ distinct contexts, so the global cap (not the PR-8
    # context-diversity safeguard) is what bounds the plan here.
    for n in range(5):
        _approved(db, f"i{n}", signals=(f"sig{n}",))
    s = ResearchScheduler(db, config=SchedulerConfig(global_dispatch_limit=3))
    assert len(s.experiment_queue()) == 3
    assert len(s.experiment_queue(limit=1)) == 1


def test_budget_excludes_in_flight_and_produced(tmp_db):
    db = tmp_db
    _campaign(db, "c", budget=3)
    _approved(db, "done", campaign_id="c")
    _produce_experiment(db, "done", "e_done")   # 1 produced
    _approved(db, "i1", campaign_id="c")
    s = ResearchScheduler(db)
    s.dispatch()                                 # i1 in-flight ⇒ 1 in-flight
    # remaining = 3 - 1 produced - 1 in-flight = 1
    assert s.remaining_budget("c") == 1


def test_unbounded_budget_is_none(tmp_db):
    db = tmp_db
    _campaign(db, "c", budget=0)
    assert ResearchScheduler(db).remaining_budget("c") is None


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------

def test_failed_idea_is_retry_eligible_then_exhausted(tmp_db):
    db = tmp_db
    _approved(db, "i1")
    s = ResearchScheduler(db, config=SchedulerConfig(max_retries=1))  # 2 attempts

    s.dispatch()                                  # attempt 1
    s.record_result("i1", ok=False, reason="boom")
    rq = s.retry_queue()
    assert [r.idea_id for r in rq] == ["i1"]
    assert rq[0].next_attempt == 2

    # The retry is planned (as a retry, not fresh) and dispatched.
    plan = s.experiment_queue()
    assert plan[0].is_retry is True and plan[0].attempt == 2
    s.dispatch()                                  # attempt 2
    s.record_result("i1", ok=False, reason="boom again")

    # Out of attempts: no longer retry-eligible, and 'exhausted' was logged.
    assert s.retry_queue() == []
    actions = [e["action"] for e in scheduler_store.list_events(idea_id="i1", db_path=db)]
    assert actions.count(scheduler_store.ACTION_DISPATCHED) == 2
    assert scheduler_store.ACTION_EXHAUSTED in actions


def test_succeeded_idea_not_retried(tmp_db):
    db = tmp_db
    _approved(db, "i1")
    s = ResearchScheduler(db)
    s.dispatch()
    s.record_result("i1", ok=True, experiment_id="e1")
    assert s.retry_queue() == []
    # Already-dispatched success is not a fresh idea either.
    assert s.experiment_queue() == []


def test_retries_precede_fresh_in_plan(tmp_db):
    db = tmp_db
    _approved(db, "old")
    _approved(db, "new")
    s = ResearchScheduler(db)
    # Dispatch one idea and fail it so it becomes a retry; the other stays fresh.
    dispatched = s.dispatch(limit=1)[0].idea_id
    s.record_result(dispatched, ok=False, reason="x")
    fresh = "new" if dispatched == "old" else "old"
    plan = [d.idea_id for d in s.experiment_queue()]
    assert plan[0] == dispatched         # retry first
    assert fresh in plan


# ---------------------------------------------------------------------------
# Reconciliation / recovery
# ---------------------------------------------------------------------------

def test_reconcile_resolves_executed_orphan_as_succeeded(tmp_db):
    db = tmp_db
    _approved(db, "i1")
    s = ResearchScheduler(db)
    s.dispatch()                                  # open dispatch
    _produce_experiment(db, "i1", "e1")           # M7 finished but no result logged
    report = s.reconcile()
    assert "i1" in report.resolved_succeeded
    assert scheduler_store.latest_event("i1", db_path=db)["action"] == \
        scheduler_store.ACTION_SUCCEEDED
    assert "i1" not in scheduler_store.in_flight_idea_ids(db_path=db)


def test_reconcile_interrupted_run_is_retry_eligible(tmp_db):
    db = tmp_db
    _approved(db, "i1")
    s = ResearchScheduler(db)
    s.dispatch()                                  # crashed mid-run; still approved
    report = s.reconcile()
    assert "i1" in report.resolved_failed and "i1" in report.still_open
    # Now retry-eligible (failed, attempts < max).
    assert [r.idea_id for r in s.retry_queue()] == ["i1"]


def test_reconcile_rejected_orphan_marked_failed(tmp_db):
    db = tmp_db
    _approved(db, "i1")
    s = ResearchScheduler(db)
    s.dispatch()
    with get_connection(db) as conn:
        conn.execute("UPDATE pending_ideas SET status='rejected' WHERE idea_id='i1'")
        conn.commit()
    report = s.reconcile()
    assert "i1" in report.resolved_failed
    ev = scheduler_store.latest_event("i1", db_path=db)
    assert ev["action"] == scheduler_store.ACTION_FAILED and ev["reason"] == "rejected"


def test_reconcile_reconciles_campaigns(tmp_db):
    db = tmp_db
    _campaign(db, "c", budget=5)
    report = ResearchScheduler(db).reconcile()
    assert report.campaigns_reconciled >= 1


def test_reconcile_is_idempotent(tmp_db):
    db = tmp_db
    _approved(db, "i1")
    s = ResearchScheduler(db)
    s.dispatch()
    s.reconcile()
    n_after_first = len(scheduler_store.list_events(idea_id="i1", db_path=db))
    s.reconcile()                                 # nothing open now
    assert len(scheduler_store.list_events(idea_id="i1", db_path=db)) == n_after_first


# ---------------------------------------------------------------------------
# Campaign queue gating
# ---------------------------------------------------------------------------

def test_campaign_queue_excludes_non_active_and_exhausted(tmp_db):
    db = tmp_db
    _campaign(db, "active", priority=0.5, budget=0)         # ACTIVE, unbounded
    _campaign(db, "draft", priority=0.5, budget=0, activate=False)  # DRAFT
    # Exhausted campaign: budget 1, already produced 1.
    _campaign(db, "full", priority=0.5, budget=1)
    _approved(db, "fi", campaign_id="full")
    _produce_experiment(db, "fi", "e_full")

    s = ResearchScheduler(db)
    cids = [c["campaign_id"] for c in s.campaign_queue()]
    assert "active" in cids
    assert "draft" not in cids
    assert "full" not in cids
