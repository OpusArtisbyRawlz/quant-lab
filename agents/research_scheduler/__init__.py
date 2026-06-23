"""
research_scheduler — Milestone 10 PR-6.

The ``ResearchScheduler`` is the deterministic *ordering / planning* layer that
sits above the unchanged M7 execution core and M9 learning core. It decides
**which already human-approved ideas should run next, and in what order**, while
enforcing per-campaign and global budgets and scheduling retries for failed
attempts.

It is emphatically NOT an executor. The scheduler:

* selects only from the ``approved`` pool (``approval_queue.list_approved``), so
  no idea can ever be dispatched without first clearing the human approval gate;
* never calls ``claim_for_execution``, builds a spec, or runs a backtest — those
  remain solely the M7 ``idea_executor``'s job;
* writes only to the append-only ``scheduler_event`` log (via
  ``scheduler_store``), so every dispatch / result / retry / reconciliation
  decision is reconstructible from stored state.

All queues are pure functions of stored state (approval-queue statuses, campaign
state, experiments, and the scheduler_event log), so the scheduler is fully
deterministic and resumable: restarting the process and recomputing yields the
same plan.
"""

from .scheduler import (
    ResearchScheduler,
    SchedulerConfig,
    DispatchItem,
    RetryItem,
    ReconcileReport,
)

__all__ = [
    "ResearchScheduler",
    "SchedulerConfig",
    "DispatchItem",
    "RetryItem",
    "ReconcileReport",
]
