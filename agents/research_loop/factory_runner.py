"""
FactoryRunner — Phase 6 P6-3.

The thin, **stateless** orchestration driver that turns the existing components
into a continuously-running Research Factory. It holds no research intelligence
and duplicates none of the scheduling, persistence, or campaign logic that already
exists — it only *coordinates*:

    discover runnable campaigns  → ResearchScheduler.campaign_queue()
    execute one deterministic tick → ResearchLoop.run_tick()
    advance campaign stop-conditions → CampaignManager.advance()
    repeat, bounded, in deterministic order

Everything durable lives in the existing stores: `loop_checkpoint` (tick
progress/resume), `campaign_state_events` (campaign lifecycle), the M11 append-only
evidence + projections. The runner keeps **no state of its own**, so a restart
simply re-discovers the runnable set and continues; `run_tick`'s checkpoint/resume
guarantees no tick is executed twice.

Determinism: campaigns are selected in `campaign_queue()`'s total order
(priority, then campaign_id); ticks run in that order; `advance` is a pure function
of stored state. Same state ⇒ same tick sequence ⇒ replayable.

Not an agent: a driver over the existing coordinators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import campaign_store
from agents.campaign_manager import CampaignManager
from agents.campaign_manager.manager import STATE_ACTIVE
from agents.research_scheduler import ResearchScheduler
from agents.research_loop.loop import ResearchLoop, LoopConfig


@dataclass
class FactoryReport:
    """Outcome of one ``run`` invocation. Pure data; derivable from the logs."""
    ticks: int = 0
    ticked: list[str] = field(default_factory=list)      # campaign_ids, in order
    rounds: int = 0
    stop_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ticks": self.ticks, "ticked": list(self.ticked),
                "rounds": self.rounds, "stop_reason": self.stop_reason}


class FactoryRunner:
    """Drives runnable campaigns via the existing ResearchLoop. Stateless."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        loop: ResearchLoop | None = None,
        scheduler: ResearchScheduler | None = None,
        campaign_manager: CampaignManager | None = None,
        loop_config: LoopConfig | None = None,
    ) -> None:
        self.db_path = db_path
        # One shared CampaignManager threaded through the Scheduler and Loop so
        # discovery, ticking, and advancement all agree on state (no parallel
        # copies). All three are the existing components — nothing new is built.
        self.campaigns = campaign_manager or CampaignManager(db_path=db_path)
        self.scheduler = scheduler or ResearchScheduler(
            db_path, campaign_manager=self.campaigns)
        self.loop = loop or ResearchLoop(
            db_path=db_path, config=loop_config,
            scheduler=self.scheduler, campaign_manager=self.campaigns,
        )

    def _runnable_ids(self) -> list[str]:
        """Runnable campaign_ids in deterministic order — delegated entirely to the
        scheduler (which already filters to ACTIVE + not-budget-exhausted and
        orders by priority, and will honour dependencies once P6-8 adds them)."""
        return [c["campaign_id"] for c in self.scheduler.campaign_queue()]

    def run(self, *, max_ticks: int | None = None,
            max_rounds: int | None = None) -> FactoryReport:
        """Drive campaigns in deterministic rounds until no campaign is runnable,
        or a bound is reached. A *round* runs one tick per runnable campaign in
        scheduler order. ``max_ticks`` bounds continuous mode (required for
        unbounded campaigns to terminate); ``max_rounds`` is an optional round cap.

        Resumable: on restart, re-invoking ``run`` re-discovers the runnable set;
        `run_tick` resumes a half-finished tick and never re-runs a completed one,
        so no execution is duplicated.
        """
        report = FactoryReport()
        while True:
            if max_ticks is not None and report.ticks >= max_ticks:
                report.stop_reason = "max_ticks"
                break
            if max_rounds is not None and report.rounds >= max_rounds:
                report.stop_reason = "max_rounds"
                break
            # Evaluate stop conditions on every live campaign first, so a campaign
            # that is *already* budget-exhausted (and thus excluded from the
            # runnable set) is still transitioned to its terminal state. Delegated
            # to the CampaignManager — the runner embeds no stop logic.
            for camp in campaign_store.list_campaigns(db_path=self.db_path):
                if camp["state"] == STATE_ACTIVE:
                    self.campaigns.advance(camp["campaign_id"])

            runnable = self._runnable_ids()
            if not runnable:
                report.stop_reason = "no_runnable_campaigns"
                break

            report.rounds += 1
            progressed = False
            for campaign_id in runnable:
                if max_ticks is not None and report.ticks >= max_ticks:
                    report.stop_reason = "max_ticks"
                    return report
                # A campaign may have left the runnable set earlier this round
                # (e.g. an ``advance`` completed it); re-check before ticking.
                if self.campaigns.current_state(campaign_id) != STATE_ACTIVE:
                    continue
                if self.campaigns.budget_exhausted(campaign_id):
                    continue
                self.loop.run_tick(campaign_id)
                report.ticks += 1
                report.ticked.append(campaign_id)
                progressed = True
                # Delegate the stop-condition transition to the campaign owner.
                self.campaigns.advance(campaign_id)

            if not progressed:
                report.stop_reason = "no_progress"
                break
        return report
