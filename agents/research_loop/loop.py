"""
loop — the deterministic, resumable ResearchLoop (M10 PR-7).

A *tick* runs a fixed six-phase sequence over one campaign:

    recover → generate → schedule → dispatch → learn → checkpoint

Each phase is bracketed by ``loop_checkpoint`` rows (``started`` / ``completed``)
so the entire tick is reconstructible from storage and resumable: on restart the
loop resumes the latest unfinished tick and **skips any phase that already
completed**, so side effects (idea generation, scheduling, execution) are never
repeated. A phase that produced no completed checkpoint is safe to re-run.

Design invariants (all asserted by tests):

* **Preserves the human approval gate** — generated ideas are enqueued as
  ``pending`` and are NEVER auto-approved. Only ``approved`` ideas are eligible
  for dispatch (the scheduler selects from ``approval_queue.list_approved`` and
  the executor refuses anything not ``approved``).
* **Preserves the M7 execution path** — dispatch delegates to the unchanged
  ``idea_executor`` (claim → spec → M5 runner → Critic → Ledger) and never
  re-implements or mutates runner logic or experiment results.
* **Preserves the M9 learning path** — learning happens inside the executor's
  SignalLibrarian; the loop only refreshes the campaign's derived progress.
* **Deterministic / idempotent / reconstructible** — every step is a pure
  function of stored state plus the checkpoint log; re-running a completed tick
  is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agents.storage.db import DB_PATH
from agents.storage import loop_store, scheduler_store, hypothesis_store
from agents.idea_generator import approval_queue, idea_executor
from agents.campaign_manager import CampaignManager
from agents.campaign_manager.manager import STATE_ACTIVE
from agents.research_strategist import ResearchStrategist
from agents.research_scheduler import ResearchScheduler, SchedulerConfig

DataDictProvider = Callable[[Any], Any]


@dataclass(frozen=True)
class LoopConfig:
    """Tunables for the loop. All deterministic; no I/O."""

    # How many ideas a single tick will schedule/dispatch (per campaign).
    dispatch_limit: int = 5
    # Whether the generate phase runs the strategist (off ⇒ pure execute loop).
    generate: bool = True
    scheduler_config: SchedulerConfig = field(default_factory=SchedulerConfig)


@dataclass
class PhaseResult:
    """Outcome of one phase within a tick."""

    phase: str
    ran: bool                      # False ⇒ skipped because already completed
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "ran": self.ran, "evidence": self.evidence}


@dataclass
class TickReport:
    """Summary of one tick."""

    tick_id: str
    campaign_id: str
    resumed: bool
    phases: list[PhaseResult] = field(default_factory=list)

    def phase(self, name: str) -> PhaseResult | None:
        for p in self.phases:
            if p.phase == name:
                return p
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tick_id": self.tick_id,
            "campaign_id": self.campaign_id,
            "resumed": self.resumed,
            "phases": [p.as_dict() for p in self.phases],
        }


class ResearchLoop:
    """Deterministic, resumable orchestrator of one campaign research tick."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        config: LoopConfig | None = None,
        strategist: ResearchStrategist | None = None,
        scheduler: ResearchScheduler | None = None,
        campaign_manager: CampaignManager | None = None,
        data_root: Path | None = None,
        completed_dir: Path | None = None,
        data_dict_provider: DataDictProvider | None = None,
    ) -> None:
        self.db_path = db_path
        self.config = config or LoopConfig()
        self.strategist = strategist or ResearchStrategist(db_path=db_path)
        self.scheduler = scheduler or ResearchScheduler(
            db_path, config=self.config.scheduler_config
        )
        self.campaigns = campaign_manager or CampaignManager(db_path=db_path)
        # Execution wiring (passed straight through to the unchanged M7 executor).
        self.data_root = data_root
        self.completed_dir = completed_dir
        self.data_dict_provider = data_dict_provider

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run_tick(self, campaign_id: str) -> TickReport:
        """Run (or resume) exactly one tick for ``campaign_id``.

        Resolves the tick_id from the checkpoint log (resuming the latest
        unfinished tick, else starting the next), then runs each phase, skipping
        any that already completed. Returns a TickReport.
        """
        tick_id, resumed = self._resolve_tick_id(campaign_id)
        report = TickReport(tick_id=tick_id, campaign_id=campaign_id,
                            resumed=resumed)

        report.phases.append(self._phase(
            tick_id, campaign_id, loop_store.PHASE_RECOVER, self._do_recover))
        report.phases.append(self._phase(
            tick_id, campaign_id, loop_store.PHASE_GENERATE, self._do_generate))
        report.phases.append(self._phase(
            tick_id, campaign_id, loop_store.PHASE_SCHEDULE, self._do_schedule))
        report.phases.append(self._phase(
            tick_id, campaign_id, loop_store.PHASE_DISPATCH, self._do_dispatch))
        report.phases.append(self._phase(
            tick_id, campaign_id, loop_store.PHASE_LEARN, self._do_learn))
        report.phases.append(self._phase(
            tick_id, campaign_id, loop_store.PHASE_CHECKPOINT, self._do_checkpoint))
        return report

    # ------------------------------------------------------------------ #
    # Phase runner — the resumability / idempotency primitive
    # ------------------------------------------------------------------ #
    def _phase(
        self,
        tick_id: str,
        campaign_id: str,
        phase: str,
        fn: Callable[[str, str], dict[str, Any]],
    ) -> PhaseResult:
        """Run one phase unless it already completed for this tick.

        Writes a ``started`` checkpoint, runs ``fn``, then a ``completed``
        checkpoint carrying the phase evidence. A phase whose ``completed`` row
        already exists is skipped entirely (its side effects already happened),
        which is exactly what makes a crashed tick resumable without repeating
        generation / scheduling / execution.
        """
        if loop_store.phase_completed(tick_id, phase, db_path=self.db_path):
            return PhaseResult(phase=phase, ran=False, evidence={"skipped": True})
        loop_store.append_checkpoint(
            tick_id, phase, loop_store.STATUS_STARTED,
            campaign_id=campaign_id, db_path=self.db_path,
        )
        evidence = fn(tick_id, campaign_id)
        loop_store.append_checkpoint(
            tick_id, phase, loop_store.STATUS_COMPLETED,
            campaign_id=campaign_id, evidence=evidence, db_path=self.db_path,
        )
        return PhaseResult(phase=phase, ran=True, evidence=evidence)

    # ------------------------------------------------------------------ #
    # Phase 1 — recover (cross-tick reconciliation; idempotent)
    # ------------------------------------------------------------------ #
    def _do_recover(self, tick_id: str, campaign_id: str) -> dict[str, Any]:
        """Bring storage to a consistent state before planning anything.

        Repairs ledger-write crashes (executing ideas with a linked experiment
        are re-ledgered, never re-run) and resolves orphaned scheduler dispatches
        from ground-truth state. Both operations are idempotent.
        """
        recovery = idea_executor.recover_incomplete_executions(
            completed_dir=self.completed_dir or idea_executor.COMPLETED_DIR,
            db_path=self.db_path,
        )
        sched_report = self.scheduler.reconcile()
        return {
            "recovered_executions": len(recovery.recovered),
            "still_incomplete": len(recovery.still_incomplete),
            "scheduler_resolved_succeeded": len(sched_report.resolved_succeeded),
            "scheduler_resolved_failed": len(sched_report.resolved_failed),
            "campaigns_reconciled": sched_report.campaigns_reconciled,
        }

    # ------------------------------------------------------------------ #
    # Phase 2 — generate (strategist; NOT auto-approved)
    # ------------------------------------------------------------------ #
    def _do_generate(self, tick_id: str, campaign_id: str) -> dict[str, Any]:
        """Expand the hypothesis frontier into new ``pending`` ideas.

        Skipped entirely when the campaign is not ACTIVE or generation is
        disabled. Every enqueued idea is ``pending`` — the human approval gate is
        untouched, so nothing generated here is dispatchable until a human
        approves it.
        """
        if not self.config.generate:
            return {"generated": 0, "skipped_reason": "generate_disabled"}
        if self.campaigns.current_state(campaign_id) != STATE_ACTIVE:
            return {"generated": 0, "skipped_reason": "campaign_not_active"}
        results = self.strategist.run_tick(campaign_id)
        return {
            "generated": len(results),
            "idea_ids": sorted(r.idea_id for r in results if r.idea_id),
        }

    # ------------------------------------------------------------------ #
    # Phase 3 — schedule (prioritize + record dispatch decisions)
    # ------------------------------------------------------------------ #
    def _do_schedule(self, tick_id: str, campaign_id: str) -> dict[str, Any]:
        """Plan and record this tick's dispatches in the scheduler_event log.

        ``scheduler.dispatch`` selects only from the approved pool (so the human
        gate is enforced), ranks via the prioritizer, respects budgets, and
        appends ``dispatched`` events. It does NOT execute anything.
        """
        plan = self.scheduler.dispatch(limit=self.config.dispatch_limit)
        return {
            "scheduled": len(plan),
            "idea_ids": [d.idea_id for d in plan],
            # PR-8 anti-mode-collapse accounting for this tick's dispatch window.
            "explore": sum(1 for d in plan if d.bucket == "explore"),
            "exploit": sum(1 for d in plan if d.bucket == "exploit"),
            "campaign_exploration": self.scheduler.exploration_stats(
                campaign_id=campaign_id),
        }

    # ------------------------------------------------------------------ #
    # Phase 4 — dispatch (execute approved ideas via the unchanged M7 path)
    # ------------------------------------------------------------------ #
    def _do_dispatch(self, tick_id: str, campaign_id: str) -> dict[str, Any]:
        """Execute the scheduled (in-flight) ideas through the M7 executor.

        For each idea the scheduler currently considers in-flight (i.e. dispatched
        but unresolved): if it is still ``approved`` it is run through the
        unchanged executor; if a previous attempt already finished it (``executed``
        / ``rejected``) the outcome is simply recorded. Each terminal outcome
        appends a ``succeeded`` / ``failed`` scheduler event, which removes the
        idea from the in-flight set — so re-running this phase is idempotent.
        """
        executed: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        in_flight = scheduler_store.in_flight_idea_ids(db_path=self.db_path)
        for idea_id in sorted(in_flight):
            idea = approval_queue.get_idea(idea_id, db_path=self.db_path)
            status = idea.get("status") if idea else None
            if status == "approved":
                res = idea_executor.run_single_approved_idea(
                    idea_id,
                    data_root=self.data_root or idea_executor.DATA_ROOT,
                    completed_dir=self.completed_dir or idea_executor.COMPLETED_DIR,
                    data_dict_provider=self.data_dict_provider,
                    db_path=self.db_path,
                )
                ok = res.outcome == "executed"
                self.scheduler.record_result(
                    idea_id, ok=ok, experiment_id=res.experiment_id,
                    reason=res.outcome if ok else ";".join(res.reasons) or res.outcome,
                )
                if ok and res.experiment_id:
                    self._stamp_node_experiment(idea_id, res.experiment_id)
                (executed if ok else failed).append(idea_id)
            elif status == "executed":
                self.scheduler.record_result(
                    idea_id, ok=True,
                    experiment_id=idea.get("experiment_id"),
                    reason="already_executed",
                )
                if idea.get("experiment_id"):
                    self._stamp_node_experiment(idea_id, idea["experiment_id"])
                executed.append(idea_id)
            elif status == "rejected":
                self.scheduler.record_result(
                    idea_id, ok=False, reason="rejected")
                failed.append(idea_id)
            else:
                # 'executing' that recover could not repair yet — leave in-flight.
                skipped.append(idea_id)
        return {"executed": executed, "failed": failed, "skipped": skipped}

    def _stamp_node_experiment(self, idea_id: str, experiment_id: str) -> None:
        """Propagate an executed idea's experiment back onto its originating
        hypothesis node (write-once). Without this stamp the strategist's
        frontier checks (``_expandable`` / ``_confirmed`` / ``_refuted``) never
        see an experiment on the node and the tree cannot evolve past the seed.
        Idempotent: skips nodes that already carry an experiment_id."""
        node = hypothesis_store.get_node_by_idea(idea_id, db_path=self.db_path)
        if node is None or node.get("experiment_id"):
            return
        hypothesis_store.link_node_experiment(
            node["node_id"], experiment_id, db_path=self.db_path)

    # ------------------------------------------------------------------ #
    # Phase 5 — learn (refresh the campaign's derived progress; idempotent)
    # ------------------------------------------------------------------ #
    def _do_learn(self, tick_id: str, campaign_id: str) -> dict[str, Any]:
        """Reconcile the campaign projection so budget/progress reflect the new
        experiments produced this tick. The M9 signal learning already happened
        inside the executor; this only refreshes the campaign's derived caches.
        """
        report = self.campaigns.reconcile(campaign_id)
        return {
            "authoritative_state": report.get("authoritative_state"),
            "budget_exhausted": self.campaigns.budget_exhausted(campaign_id),
        }

    # ------------------------------------------------------------------ #
    # Phase 6 — checkpoint (terminal marker; makes the tick reconstructible)
    # ------------------------------------------------------------------ #
    def _do_checkpoint(self, tick_id: str, campaign_id: str) -> dict[str, Any]:
        return {"tick_id": tick_id, "completed": True}

    # ------------------------------------------------------------------ #
    # tick_id resolution
    # ------------------------------------------------------------------ #
    def _resolve_tick_id(self, campaign_id: str) -> tuple[str, bool]:
        """Return ``(tick_id, resumed)``.

        If the campaign's most-recent tick is unfinished (no completed
        ``checkpoint`` phase), resume it; otherwise start the next sequential
        tick. The id is deterministic and derived purely from the stored
        checkpoint log, so it is reconstructible across restarts.
        """
        prefix = f"{campaign_id}#t"
        ticks = [
            t for t in loop_store.distinct_tick_ids(db_path=self.db_path)
            if t.startswith(prefix)
        ]
        if ticks:
            last = ticks[-1]
            if not loop_store.tick_completed(last, db_path=self.db_path):
                return last, True
        return f"{prefix}{len(ticks) + 1:04d}", False
