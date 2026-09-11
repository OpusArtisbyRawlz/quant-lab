"""
PortfolioPlanner — Phase 6 P6-10.

A **pure planning function** (a module/class, NOT a new agent) that turns the stored
portfolio + campaign state into a **deterministic execution plan**: the admitted,
ordered set of runnable campaign_ids per ACTIVE portfolio. It reads only stored state
and returns a plan — it **executes nothing, mutates no state, allocates no budget,
and runs no experiments**. It does not touch the ResearchScheduler or FactoryRunner.

Plan (per the approved design §8), for each ACTIVE portfolio:

    1. runnable = member campaigns that are ACTIVE, not budget-exhausted, and whose
       dependencies are satisfied (§4). "Trigger fired" is reflected by the ACTIVE
       state — the planner does NOT evaluate schedule/event trigger predicates or
       repeat re-entry; those are owned by the CampaignManager (§3/§6, P6-11).
    2. order by the portfolio's scheduling_policy over the P6-8 planning fields:
         priority      → (-priority, campaign_id)
         eig_weighted  → (-priority, -EIG, campaign_id)     # static priority, then dynamic EIG
         round_robin   → deferred (needs a logical-tick cursor, not yet stored);
                         falls back to priority ordering.
       then apply a stable, dependency-aware refinement so a runnable prerequisite
       precedes a runnable dependent (topological, policy order preserved otherwise).
    3. admit up to concurrency_limit (0 = unbounded).

Determinism / replay-safety: every input (state, priority, EIG, dependencies,
concurrency_limit) is a pure function of stored state; every ordering breaks ties on
campaign_id, so the same stored state always yields the identical plan. No wall-clock,
no randomness, no mutation.

Inputs are exactly the approved Phase-6 fields: ``priority``, ``trigger_spec``
(state-based only), ``depends_on``, ``expected_information_gain``, ``eig_spec``
(read-through), ``repeat_spec`` (state-based only). EIG is read from the cached
``expected_information_gain`` column (populated by P6-13); absent ⇒ 0.0, so
eig_weighted degrades gracefully to priority ordering before P6-13 lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import campaign_store, portfolio_store
from agents.storage.portfolio_store import (
    PORTFOLIO_ACTIVE,
    POLICY_PRIORITY,
    POLICY_ROUND_ROBIN,
    POLICY_EIG_WEIGHTED,
)
from agents.campaign_manager import CampaignManager


@dataclass(frozen=True)
class PortfolioPlan:
    """One portfolio's deterministic plan. Pure data; derivable from stored state."""
    portfolio_id: str
    policy: str
    admitted: list[str] = field(default_factory=list)   # campaign_ids, in order
    concurrency_limit: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"portfolio_id": self.portfolio_id, "policy": self.policy,
                "admitted": list(self.admitted),
                "concurrency_limit": self.concurrency_limit}


class PortfolioPlanner:
    """Pure planner over stored portfolio + campaign state. Holds no state."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        campaign_manager: CampaignManager | None = None,
    ) -> None:
        self.db_path = db_path
        # Reuse the existing CampaignManager for authoritative (event-derived) state
        # and budget derivation — no parallel state logic.
        self.campaigns = campaign_manager or CampaignManager(db_path=db_path)

    # -- public API --------------------------------------------------------

    def plan_all(self) -> list[PortfolioPlan]:
        """Deterministic plans for every ACTIVE portfolio, ordered by portfolio_id.
        Standalone campaigns (no portfolio) are intentionally out of scope — they
        keep today's scheduler behaviour, which the planner does not touch."""
        portfolios = portfolio_store.list_portfolios(
            state=PORTFOLIO_ACTIVE, db_path=self.db_path
        )
        plans = [self.plan(p["portfolio_id"]) for p in portfolios]
        return sorted(plans, key=lambda pl: pl.portfolio_id)

    def plan(self, portfolio_id: str) -> PortfolioPlan:
        """The deterministic plan for one portfolio. A non-ACTIVE (PAUSED/ARCHIVED)
        or unknown portfolio yields an empty plan — its campaigns are not admitted."""
        portfolio = portfolio_store.get_portfolio(portfolio_id, db_path=self.db_path)
        policy = (portfolio or {}).get("scheduling_policy", POLICY_PRIORITY)
        limit = int((portfolio or {}).get("concurrency_limit", 0) or 0)

        if portfolio is None or (
            portfolio_store.reconstruct_portfolio_state_from_events(
                portfolio_id, db_path=self.db_path
            ) != PORTFOLIO_ACTIVE
        ):
            return PortfolioPlan(portfolio_id, policy, [], limit)

        members = [
            campaign_store.get_campaign(cid, db_path=self.db_path)
            for cid in self.campaigns.campaigns_in_portfolio(portfolio_id)
        ]
        members = [m for m in members if m is not None]

        # Campaign eligibility (state + budget + trigger + dependencies) is obtained
        # from the CampaignManager — the single owner of trigger/repeat/dependency
        # evaluation (P6-11). The planner never re-derives it, so there is no
        # duplicate trigger logic; the planner only ORDERS the eligible set.
        runnable = [
            m for m in members
            if self.campaigns.is_eligible(m["campaign_id"])
        ]
        ordered = self._order(runnable, policy)
        ordered = self._dependency_aware(ordered)

        admitted = ordered if limit <= 0 else ordered[:limit]
        return PortfolioPlan(portfolio_id, policy, admitted, limit)

    # -- ordering (pure) ---------------------------------------------------

    def _order(self, runnable: list[dict[str, Any]], policy: str) -> list[str]:
        """Order the runnable campaigns by the portfolio policy. Every key ends on
        campaign_id, so ordering is a total order (deterministic)."""
        if policy == POLICY_EIG_WEIGHTED:
            key = lambda c: (-campaign_store.campaign_priority(c),
                             -self._eig(c), c["campaign_id"])
        else:
            # POLICY_PRIORITY, and POLICY_ROUND_ROBIN (deferred → priority fallback),
            # and any unknown policy: stable priority ordering.
            key = lambda c: (-campaign_store.campaign_priority(c), c["campaign_id"])
        return [c["campaign_id"] for c in sorted(runnable, key=key)]

    @staticmethod
    def _eig(campaign: dict[str, Any]) -> float:
        """Cached campaign EIG (P6-8 ``expected_information_gain`` column, populated
        by P6-13). Absent ⇒ 0.0, so eig_weighted degrades to priority ordering."""
        v = campaign.get("expected_information_gain")
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _dependency_aware(self, ordered_ids: list[str]) -> list[str]:
        """Stable, dependency-aware refinement of a policy-ordered id list: a runnable
        prerequisite precedes a runnable dependent, policy order preserved otherwise.

        Only edges *among the runnable set* matter (deps outside it are already
        satisfied by the runnable filter). Deterministic Kahn's algorithm seeded by
        the policy order; a cycle (which §4 forbids at definition time) can't stall —
        remaining nodes fall back to policy order."""
        in_set = set(ordered_ids)
        # prereqs[x] = runnable campaigns x depends on (an ordering constraint).
        prereqs: dict[str, set[str]] = {}
        for cid in ordered_ids:
            camp = campaign_store.get_campaign(cid, db_path=self.db_path) or {}
            prereqs[cid] = {
                dep_id for dep_id, _ in campaign_store.normalized_depends_on(camp)
                if dep_id in in_set
            }

        emitted: list[str] = []
        done: set[str] = set()
        remaining = list(ordered_ids)          # already in policy order
        while remaining:
            progressed = False
            for cid in list(remaining):
                if prereqs[cid] <= done:       # all runnable prereqs already emitted
                    emitted.append(cid)
                    done.add(cid)
                    remaining.remove(cid)
                    progressed = True
                    break                      # restart scan → keep policy order stable
            if not progressed:
                # Cycle among the remaining (design-forbidden). Emit in policy order.
                emitted.extend(remaining)
                break
        return emitted
