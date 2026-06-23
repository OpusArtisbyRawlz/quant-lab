"""
scheduler — the deterministic ResearchScheduler (M10 PR-6).

Responsibilities (and only these):

* ``campaign_queue``   — runnable campaigns, in deterministic dispatch order.
* ``priority_queue``   — approved ideas ranked by Research Value (PR-5), with
                         in-flight ideas excluded.
* ``experiment_queue`` — the concrete dispatch plan (due retries first, then
                         fresh ideas), respecting per-campaign + global budgets.
* ``retry_queue``      — failed ideas still within their retry allowance.
* budget accounting    — per-campaign remaining budget and a global cap.
* ``dispatch``         — append ``dispatched`` events for the plan (no execution).
* ``record_result``    — append ``succeeded`` / ``failed`` events.
* ``reconcile``        — startup recovery: resolve orphaned dispatches from
                         ground-truth stored state and reconcile campaigns.

Every decision is derived from stored state and recorded in the append-only
``scheduler_event`` log, so the scheduler is deterministic, resumable, and
auditable. It never approves or executes anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.storage import scheduler_store, campaign_store, ledger_store
from agents.storage.db import DB_PATH
from agents.idea_generator import approval_queue
from agents.campaign_manager.manager import CampaignManager
from agents.campaign_manager import manager as cm_states
from agents.research_prioritizer.prioritizer import (
    ResearchPrioritizer,
    PrioritizerConfig,
)
from agents.research_quota import (
    ExplorationPlanner,
    QuotaConfig,
    Candidate,
)

# Campaign states whose ideas the scheduler is allowed to dispatch.
_RUNNABLE_CAMPAIGN_STATES = frozenset({cm_states.STATE_ACTIVE})

# Sentinel used to request the non-campaign (ad-hoc) ranked group.
_ADHOC = object()


# ---------------------------------------------------------------------------
# Config + result dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SchedulerConfig:
    """Tunables for the scheduler. All deterministic; no I/O."""

    # Number of *retries* allowed after the first attempt. max_attempts =
    # max_retries + 1. So max_retries=2 ⇒ up to 3 dispatches per idea.
    max_retries: int = 2
    # Hard cap on how many ideas a single dispatch() call will plan, across all
    # campaigns. None ⇒ no global cap (still bounded by approved pool + budgets).
    global_dispatch_limit: int | None = None
    # Reasons that mark an interrupted dispatch as retry-eligible on recovery.
    interrupted_reason: str = "interrupted"
    # PR-8 anti-mode-collapse safeguards over the fresh-idea dispatch window.
    # Fraction of a dispatch window reserved for explore-bucket ideas; None ⇒
    # fall back to the prioritizer's exploration_fraction.
    exploration_fraction: float | None = None
    # Max fresh ideas sharing one M9 context key in a single dispatch window;
    # None ⇒ context diversity is not enforced. Retries are exempt.
    max_per_context: int | None = 2

    @property
    def max_attempts(self) -> int:
        return int(self.max_retries) + 1


@dataclass(frozen=True)
class DispatchItem:
    """One planned dispatch: an approved idea chosen to run next."""

    idea_id: str
    campaign_id: str | None
    attempt: int                 # 1 for first try, 2.. for retries
    is_retry: bool
    rank: int                    # position within the computed plan (0-based)
    research_value: float | None  # prioritizer score (None for pure retries)
    reason: str = ""
    bucket: str | None = None    # PR-8 "explore" | "exploit" (None for retries)

    def as_dict(self) -> dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "campaign_id": self.campaign_id,
            "attempt": self.attempt,
            "is_retry": self.is_retry,
            "rank": self.rank,
            "research_value": self.research_value,
            "reason": self.reason,
            "bucket": self.bucket,
        }


@dataclass(frozen=True)
class RetryItem:
    """A failed idea that is still eligible for another attempt."""

    idea_id: str
    campaign_id: str | None
    attempts_made: int
    next_attempt: int
    last_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "campaign_id": self.campaign_id,
            "attempts_made": self.attempts_made,
            "next_attempt": self.next_attempt,
            "last_reason": self.last_reason,
        }


@dataclass
class ReconcileReport:
    """Summary of a reconcile() pass."""

    resolved_succeeded: list[str] = field(default_factory=list)
    resolved_failed: list[str] = field(default_factory=list)
    campaigns_reconciled: int = 0
    still_open: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolved_succeeded": list(self.resolved_succeeded),
            "resolved_failed": list(self.resolved_failed),
            "campaigns_reconciled": self.campaigns_reconciled,
            "still_open": list(self.still_open),
        }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class ResearchScheduler:
    """Deterministic dispatch planner over the human-approved idea pool."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        config: SchedulerConfig | None = None,
        prioritizer: ResearchPrioritizer | None = None,
        campaign_manager: CampaignManager | None = None,
    ) -> None:
        self.db_path = db_path
        self.config = config or SchedulerConfig()
        self.prioritizer = prioritizer or ResearchPrioritizer(
            db_path, config=PrioritizerConfig()
        )
        self.campaigns = campaign_manager or CampaignManager(db_path)
        # PR-8 exploration quota + context-diversity planner. The quota fraction
        # defaults to the prioritizer's own exploration_fraction when not set, so
        # the scheduler and prioritizer share one exploration policy.
        self._exploration_fraction = (
            self.config.exploration_fraction
            if self.config.exploration_fraction is not None
            else self.prioritizer.config.exploration_fraction
        )
        self.planner = ExplorationPlanner(
            QuotaConfig(
                exploration_fraction=self._exploration_fraction,
                max_per_context=self.config.max_per_context,
            )
        )

    # ------------------------------------------------------------------ #
    # Queue 1 — campaigns
    # ------------------------------------------------------------------ #
    def campaign_queue(self) -> list[dict[str, Any]]:
        """Runnable campaigns in deterministic dispatch order.

        A campaign is runnable iff its *event-derived* state is ACTIVE and it is
        not budget-exhausted. Ordered by descending ``goal_spec.priority`` then
        ascending ``campaign_id`` (a total order ⇒ identical inputs always plan
        identically).
        """
        runnable: list[dict[str, Any]] = []
        for camp in campaign_store.list_campaigns(db_path=self.db_path):
            cid = camp["campaign_id"]
            if self.campaigns.current_state(cid) not in _RUNNABLE_CAMPAIGN_STATES:
                continue
            if self.campaigns.budget_exhausted(cid):
                continue
            runnable.append(camp)
        runnable.sort(key=lambda c: (-self._priority(c), c["campaign_id"]))
        return runnable

    # ------------------------------------------------------------------ #
    # Queue 2 — priority (approved ideas, ranked)
    # ------------------------------------------------------------------ #
    def priority_queue(
        self, *, campaign_id: Any = None, include_in_flight: bool = False
    ) -> list[Any]:
        """Approved ideas ranked by Research Value, in-flight excluded.

        ``campaign_id`` selects the subset to rank:

        * ``None`` (default) — the whole approved pool;
        * a ``str`` — only that campaign's approved ideas;
        * the ``_ADHOC`` sentinel — only ideas with no campaign attribution.
        """
        in_flight = (
            set() if include_in_flight
            else scheduler_store.in_flight_idea_ids(db_path=self.db_path)
        )
        ideas = [
            i for i in approval_queue.list_approved(db_path=self.db_path)
            if i["idea_id"] not in in_flight
        ]
        if campaign_id is _ADHOC:
            ideas = [i for i in ideas if not i.get("campaign_id")]
        elif campaign_id is not None:
            ideas = [i for i in ideas if i.get("campaign_id") == campaign_id]
        return self.prioritizer.rank(ideas)

    # ------------------------------------------------------------------ #
    # Queue 3 — retries
    # ------------------------------------------------------------------ #
    def retry_queue(self) -> list[RetryItem]:
        """Failed ideas still within their retry allowance, oldest-failure first.

        Eligibility is derived purely from the event log: the idea's most-recent
        action is ``failed`` and it has been dispatched fewer than
        ``max_attempts`` times. Ideas whose latest action is open
        (dispatched/retry_scheduled), succeeded, or exhausted are excluded.
        """
        out: list[RetryItem] = []
        latest = scheduler_store.latest_event_per_idea(db_path=self.db_path)
        for idea_id, ev in latest.items():
            if ev["action"] != scheduler_store.ACTION_FAILED:
                continue
            attempts = scheduler_store.dispatch_count(idea_id, db_path=self.db_path)
            if attempts >= self.config.max_attempts:
                continue
            out.append(
                RetryItem(
                    idea_id=idea_id,
                    campaign_id=ev.get("campaign_id"),
                    attempts_made=attempts,
                    next_attempt=attempts + 1,
                    last_reason=ev.get("reason"),
                )
            )
        # Deterministic: oldest failing event first (its row id), tie by idea_id.
        out.sort(key=lambda r: (latest[r.idea_id]["id"], r.idea_id))
        return out

    # ------------------------------------------------------------------ #
    # Budget accounting
    # ------------------------------------------------------------------ #
    def remaining_budget(self, campaign_id: str) -> int | None:
        """Experiments a campaign may still produce, or None if unbounded.

        ``budget_experiments <= 0`` ⇒ unbounded (None). Otherwise the remaining
        budget is ``budget - produced - in_flight`` where *produced* is the
        canonical campaign-experiment count and *in_flight* is the campaign's
        open (unresolved) dispatches. Never negative.
        """
        camp = campaign_store.get_campaign(campaign_id, db_path=self.db_path)
        if camp is None:
            return 0
        budget = int(camp.get("budget_experiments") or 0)
        if budget <= 0:
            return None
        produced = campaign_store.count_campaign_experiments(
            campaign_id, db_path=self.db_path
        )
        in_flight = scheduler_store.in_flight_count_by_campaign(
            db_path=self.db_path
        ).get(campaign_id, 0)
        return max(0, budget - produced - in_flight)

    # ------------------------------------------------------------------ #
    # Queue 4 — experiment (the dispatch plan)
    # ------------------------------------------------------------------ #
    def experiment_queue(self, limit: int | None = None) -> list[DispatchItem]:
        """The concrete dispatch plan, deterministically ordered.

        Order: (1) due retries first (oldest failure first), then (2) fresh
        approved ideas grouped by campaign_queue order — campaign ideas in
        ranked order, then ad-hoc (non-campaign) ideas in ranked order. The plan
        respects per-campaign remaining budget and an optional global limit
        (``limit`` arg, else ``config.global_dispatch_limit``). No idea appears
        twice. This method is pure (no writes)."""
        cap = self._effective_limit(limit)
        plan: list[DispatchItem] = []
        chosen: set[str] = set()
        # Track budget consumed *within this plan* so we never over-commit.
        budget_left: dict[str, int | None] = {}
        rank = 0

        def _budget_for(cid: str | None) -> int | None:
            if cid is None:
                return None  # ad-hoc ideas are not campaign-budgeted
            if cid not in budget_left:
                budget_left[cid] = self.remaining_budget(cid)
            return budget_left[cid]

        def _consume(cid: str | None) -> None:
            if cid is None:
                return
            rem = budget_left.get(cid)
            if rem is not None:
                budget_left[cid] = rem - 1

        # ---- (1) due retries ----
        for r in self.retry_queue():
            if cap is not None and len(plan) >= cap:
                break
            if r.idea_id in chosen:
                continue
            rem = _budget_for(r.campaign_id)
            if rem is not None and rem <= 0:
                continue
            plan.append(
                DispatchItem(
                    idea_id=r.idea_id,
                    campaign_id=r.campaign_id,
                    attempt=r.next_attempt,
                    is_retry=True,
                    rank=rank,
                    research_value=None,
                    reason="retry",
                )
            )
            chosen.add(r.idea_id)
            _consume(r.campaign_id)
            rank += 1

        # ---- (2) fresh ideas, campaign-ordered then ad-hoc ----
        # Build a single value-ordered candidate stream: each runnable campaign's
        # ranked ideas (in campaign_queue priority order), then ad-hoc ideas. The
        # incoming order IS the value order the exploration planner preserves.
        ranked_groups: list[list[Any]] = []
        for camp in self.campaign_queue():
            ranked_groups.append(
                self.priority_queue(campaign_id=camp["campaign_id"])
            )
        ranked_groups.append(self.priority_queue(campaign_id=_ADHOC))

        candidates: list[Candidate] = []
        order = 0
        for group in ranked_groups:
            for ranked in group:
                idea_id = ranked.idea_id
                if idea_id in chosen:
                    continue
                # A fresh idea is one with no open/terminal scheduler history that
                # would make it a retry; if it already has events it is handled
                # by retry_queue, so skip ideas already dispatched/exhausted.
                if not self._is_fresh(idea_id):
                    continue
                b = ranked.breakdown
                ev = b.evidence or {}
                candidates.append(Candidate(
                    idea_id=idea_id,
                    bucket=b.bucket,
                    context_key=(
                        ev.get("primary_signal"), ev.get("market"),
                        ev.get("universe"), ev.get("bar_type"),
                    ),
                    order=order,
                    campaign_id=ranked.idea.get("campaign_id"),
                    research_value=b.research_value,
                    payload=ranked,
                ))
                order += 1

        # The fresh window is whatever dispatch budget remains after retries.
        window = (
            len(candidates) if cap is None else max(0, cap - len(plan))
        )

        def _admit(c: Candidate) -> bool:
            rem = _budget_for(c.campaign_id)
            if rem is not None and rem <= 0:
                return False
            _consume(c.campaign_id)
            return True

        quota_plan = self.planner.plan(candidates, window, accept=_admit)
        for c in quota_plan.selected:
            plan.append(DispatchItem(
                idea_id=c.idea_id,
                campaign_id=c.campaign_id,
                attempt=1,
                is_retry=False,
                rank=rank,
                research_value=c.research_value,
                reason="fresh",
                bucket=c.bucket,
            ))
            chosen.add(c.idea_id)
            rank += 1
        return plan

    # ------------------------------------------------------------------ #
    # dispatch — the only mutating planning method
    # ------------------------------------------------------------------ #
    def dispatch(self, limit: int | None = None) -> list[DispatchItem]:
        """Compute the plan and record one ``dispatched`` event per item.

        Returns the dispatched plan. This writes ONLY to scheduler_event; it does
        not claim, spec, or execute any idea. The attempt number written equals
        the idea's prior dispatch count + 1, so the log is the retry source of
        truth.
        """
        plan = self.experiment_queue(limit=limit)
        for item in plan:
            attempt = scheduler_store.dispatch_count(
                item.idea_id, db_path=self.db_path
            ) + 1
            scheduler_store.append_event(
                item.idea_id,
                scheduler_store.ACTION_DISPATCHED,
                campaign_id=item.campaign_id,
                attempt=attempt,
                reason=item.reason,
                evidence={
                    "rank": item.rank,
                    "is_retry": item.is_retry,
                    "research_value": item.research_value,
                    "bucket": item.bucket,
                },
                db_path=self.db_path,
            )
        return plan

    # ------------------------------------------------------------------ #
    # exploration accounting — reconstructed purely from the dispatch log
    # ------------------------------------------------------------------ #
    def exploration_stats(
        self, *, campaign_id: str | None = None
    ) -> dict[str, Any]:
        """Campaign-level explore/exploit accounting, derived from the log.

        Counts every ``dispatched`` event by the ``bucket`` recorded in its
        evidence. Because it reads only the append-only ``scheduler_event`` log,
        the accounting is fully reconstructible from storage and therefore
        survives process restarts — a fresh ResearchScheduler instance reports
        the same numbers (PR-8 "restart/recovery preserves quota state").
        """
        explore = exploit = unknown = 0
        for e in scheduler_store.list_events(
            action=scheduler_store.ACTION_DISPATCHED, db_path=self.db_path
        ):
            if campaign_id is not None and e.get("campaign_id") != campaign_id:
                continue
            ev = e.get("evidence")
            bucket = ev.get("bucket") if isinstance(ev, dict) else None
            if bucket == "explore":
                explore += 1
            elif bucket == "exploit":
                exploit += 1
            else:
                unknown += 1
        total = explore + exploit + unknown
        return {
            "explore": explore,
            "exploit": exploit,
            "unknown": unknown,
            "total": total,
            "explore_fraction": round(explore / total, 6) if total else 0.0,
        }

    # ------------------------------------------------------------------ #
    # record_result — outcome of a dispatched run (written by the loop layer)
    # ------------------------------------------------------------------ #
    def record_result(
        self,
        idea_id: str,
        *,
        ok: bool,
        experiment_id: str | None = None,
        reason: str = "",
    ) -> int:
        """Append a ``succeeded`` / ``failed`` event for a dispatched idea.

        The attempt number is the idea's current dispatch count (i.e. the attempt
        that just ran). If the idea has now failed its final allowed attempt, an
        ``exhausted`` event is appended immediately after the ``failed`` event so
        the terminal state is explicit in the log.
        """
        attempt = scheduler_store.dispatch_count(idea_id, db_path=self.db_path)
        latest = scheduler_store.latest_event(idea_id, db_path=self.db_path)
        campaign_id = latest.get("campaign_id") if latest else None
        action = (
            scheduler_store.ACTION_SUCCEEDED if ok
            else scheduler_store.ACTION_FAILED
        )
        row_id = scheduler_store.append_event(
            idea_id,
            action,
            campaign_id=campaign_id,
            experiment_id=experiment_id,
            attempt=attempt,
            reason=reason,
            db_path=self.db_path,
        )
        if (not ok) and attempt >= self.config.max_attempts:
            scheduler_store.append_event(
                idea_id,
                scheduler_store.ACTION_EXHAUSTED,
                campaign_id=campaign_id,
                experiment_id=experiment_id,
                attempt=attempt,
                reason="max_attempts_reached",
                db_path=self.db_path,
            )
        return row_id

    # ------------------------------------------------------------------ #
    # reconcile — startup recovery from ground-truth stored state
    # ------------------------------------------------------------------ #
    def reconcile(self) -> ReconcileReport:
        """Resolve interrupted dispatches and reconcile campaigns.

        For every idea whose most-recent scheduler event is an *open* dispatch
        (dispatched / retry_scheduled), decide its true outcome from ground-truth
        stored state:

        * the idea is ``executed`` (M7 finished) ⇒ append ``succeeded``;
        * the idea is ``rejected`` ⇒ append ``failed`` (reason ``rejected``);
        * otherwise (still approved/executing or no experiment) the run was
          interrupted ⇒ append ``failed`` with the interrupted reason so it
          becomes retry-eligible.

        Campaign projections are then reconciled via the CampaignManager (its own
        event log is ground truth). Returns a ReconcileReport.
        """
        report = ReconcileReport()
        open_ids = scheduler_store.in_flight_idea_ids(db_path=self.db_path)
        for idea_id in sorted(open_ids):
            idea = approval_queue.get_idea(idea_id, db_path=self.db_path)
            latest = scheduler_store.latest_event(idea_id, db_path=self.db_path)
            campaign_id = latest.get("campaign_id") if latest else None
            attempt = scheduler_store.dispatch_count(
                idea_id, db_path=self.db_path
            )
            status = idea.get("status") if idea else None
            exp_id = idea.get("experiment_id") if idea else None

            if status == "executed":
                scheduler_store.append_event(
                    idea_id, scheduler_store.ACTION_SUCCEEDED,
                    campaign_id=campaign_id, experiment_id=exp_id,
                    attempt=attempt, reason="recovered_executed",
                    db_path=self.db_path,
                )
                report.resolved_succeeded.append(idea_id)
            elif status == "rejected":
                scheduler_store.append_event(
                    idea_id, scheduler_store.ACTION_FAILED,
                    campaign_id=campaign_id, experiment_id=exp_id,
                    attempt=attempt, reason="rejected",
                    db_path=self.db_path,
                )
                report.resolved_failed.append(idea_id)
            else:
                # approved / executing / missing → interrupted, retry-eligible.
                scheduler_store.append_event(
                    idea_id, scheduler_store.ACTION_FAILED,
                    campaign_id=campaign_id, experiment_id=exp_id,
                    attempt=attempt, reason=self.config.interrupted_reason,
                    db_path=self.db_path,
                )
                report.resolved_failed.append(idea_id)
                report.still_open.append(idea_id)

        report.campaigns_reconciled = len(self.campaigns.reconcile_all())
        return report

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _priority(camp: dict[str, Any]) -> float:
        goal = camp.get("goal_spec") or {}
        try:
            return float(goal.get("priority", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _effective_limit(self, limit: int | None) -> int | None:
        if limit is not None:
            return max(0, int(limit))
        if self.config.global_dispatch_limit is not None:
            return max(0, int(self.config.global_dispatch_limit))
        return None

    def _is_fresh(self, idea_id: str) -> bool:
        """An idea is fresh iff it has never been dispatched. Ideas with prior
        events are handled exclusively by the retry path (or are terminal)."""
        return scheduler_store.dispatch_count(idea_id, db_path=self.db_path) == 0
