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
# P6-13: reuse the FROZEN M11 pure budget allocator (water-filling, a_max
# anti-monopoly ceiling, integer-floor). We call it — never modify it — so the
# campaign-level split reuses the exact per-hypothesis budget math one level up
# (design §9: "mirroring the M11 budget's a_max"). No budget logic is duplicated
# and no scoring is invented.
from agents.research_intelligence import budget as m11_budget

# Portfolio budget-allocation policies (budget_spec.mode). Names mirror §9's
# "equal (round-robin), priority-proportional, or EIG-proportional".
BUDGET_MODE_EQUAL = "equal"
BUDGET_MODE_PRIORITY = "priority_proportional"
BUDGET_MODE_EIG = "eig_proportional"
DEFAULT_BUDGET_MODE = BUDGET_MODE_EQUAL


@dataclass(frozen=True)
class PortfolioPlan:
    """One portfolio's deterministic plan. Pure data; derivable from stored state."""
    portfolio_id: str
    policy: str
    admitted: list[str] = field(default_factory=list)   # campaign_ids, in dependency-aware order
    concurrency_limit: int = 0
    # P6-12: runnable campaigns excluded because they sit in (or depend on) a
    # dependency cycle — §4 requires such campaigns be rejected, so they are never
    # admitted. Sorted, deterministic; empty in the normal (acyclic) case.
    excluded_cycles: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"portfolio_id": self.portfolio_id, "policy": self.policy,
                "admitted": list(self.admitted),
                "concurrency_limit": self.concurrency_limit,
                "excluded_cycles": list(self.excluded_cycles)}


@dataclass(frozen=True)
class BudgetAllocation:
    """A portfolio's deterministic budget split across its admitted campaigns.

    Pure data derivable from stored state. ``allocations`` maps each admitted
    campaign to its integer experiment-slot share for the window; campaigns not in
    the map (ineligible / paused / archived / cyclic — never admitted) receive
    nothing. ``headroom`` is the portfolio budget left unassigned (the a_max ceiling
    and per-campaign clamping leave explicit slack — budget is never force-spent)."""
    portfolio_id: str
    mode: str
    total: int
    allocations: dict[str, int] = field(default_factory=dict)
    headroom: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"portfolio_id": self.portfolio_id, "mode": self.mode,
                "total": self.total, "allocations": dict(self.allocations),
                "headroom": self.headroom}


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

    def allocate_budget_all(self) -> list[BudgetAllocation]:
        """Deterministic budget allocations for every ACTIVE portfolio, ordered by
        portfolio_id. Each portfolio is allocated independently."""
        portfolios = portfolio_store.list_portfolios(
            state=PORTFOLIO_ACTIVE, db_path=self.db_path
        )
        allocs = [self.allocate_budget(p["portfolio_id"]) for p in portfolios]
        return sorted(allocs, key=lambda a: a.portfolio_id)

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
        policy_ordered = self._order(runnable, policy)
        # Dependency-aware refinement + cycle rejection (§4): cyclic campaigns (and
        # any that transitively depend on a cycle) cannot be validly ordered, so they
        # are excluded from the admitted plan rather than scheduled.
        ordered, excluded = self._topo_order(policy_ordered)

        admitted = ordered if limit <= 0 else ordered[:limit]
        return PortfolioPlan(portfolio_id, policy, admitted, limit,
                             excluded_cycles=excluded)

    def detect_cycles(self, portfolio_id: str) -> list[str]:
        """Pure dependency-cycle check over a portfolio's member campaigns (the §4
        topological check). Returns the sorted campaign_ids that cannot be
        topologically ordered — i.e. those in a dependency cycle, plus any that
        transitively depend on one. Empty for a valid DAG. Reads only; mutates
        nothing. Edges are restricted to intra-portfolio members (a dependency on a
        non-member is an external prerequisite, not part of this portfolio's graph)."""
        members = self.campaigns.campaigns_in_portfolio(portfolio_id)
        return self._unschedulable(members)

    # -- budget allocation (P6-13, pure policy) ----------------------------

    def allocate_budget(self, portfolio_id: str) -> BudgetAllocation:
        """Deterministically split a portfolio's window budget across its admitted
        campaigns (design §9). Pure: reads stored state, mutates nothing, and never
        touches historical evidence.

        Reuses the plan's admitted set (P6-12: eligible, acyclic, concurrency-limited),
        so ineligible / paused / archived / cyclic campaigns receive nothing. The
        split reuses the FROZEN M11 `budget.allocate` (EVOI-proportional water-filling
        + a_max anti-monopoly ceiling + integer floor) with per-campaign *weights*:

          - ``equal``               → uniform weights;
          - ``priority_proportional`` → weights = campaign priority (P6-8);
          - ``eig_proportional``    → weights = cached ``expected_information_gain``
                                       (P6-8 column, populated by P6-14; 0 until then
                                       ⇒ degrades to uniform — P6-13 never aggregates
                                       raw EVOI, that stays P6-14's job).

        Each share is then clamped to the campaign's own ``budget_experiments`` when
        that is > 0 (0 = unbounded); slots freed by the a_max ceiling or clamping
        become explicit ``headroom`` — budget is never force-spent. ``budget_spec``
        keys: ``total`` (window slots, default 0), ``mode`` (default equal), and
        optional ``a_max``/``a_min`` overriding the M11 ceiling/floor.
        """
        portfolio = portfolio_store.get_portfolio(portfolio_id, db_path=self.db_path)
        spec = (portfolio or {}).get("budget_spec") or {}
        mode = spec.get("mode", DEFAULT_BUDGET_MODE)
        total = int(spec.get("total", 0) or 0)

        admitted = self.plan(portfolio_id).admitted
        if not admitted or total <= 0:
            return BudgetAllocation(portfolio_id, mode, total, {}, headroom=max(total, 0))

        campaigns = {
            cid: (campaign_store.get_campaign(cid, db_path=self.db_path) or {})
            for cid in admitted
        }
        weights = {cid: self._budget_weight(campaigns[cid], mode) for cid in admitted}

        policy = m11_budget.BudgetPolicy(
            a_max=float(spec.get("a_max", m11_budget.DEFAULT_POLICY.a_max)),
            a_min=float(spec.get("a_min", m11_budget.DEFAULT_POLICY.a_min)),
        )
        raw = m11_budget.allocate(weights, set(admitted), total, policy)

        allocations: dict[str, int] = {}
        for cid in admitted:
            slots = raw[cid].b_experiments
            cap = int(campaigns[cid].get("budget_experiments", 0) or 0)
            if cap > 0:
                slots = min(slots, cap)          # respect the campaign's own cap
            allocations[cid] = slots
        headroom = total - sum(allocations.values())
        return BudgetAllocation(portfolio_id, mode, total, allocations, headroom=headroom)

    def _budget_weight(self, campaign: dict[str, Any], mode: str) -> float:
        """Per-campaign allocation weight for a budget mode (≥ 0). Reuses the P6-8
        priority accessor and the cached EIG column — no new scoring is invented."""
        if mode == BUDGET_MODE_PRIORITY:
            return max(campaign_store.campaign_priority(campaign), 0.0)
        if mode == BUDGET_MODE_EIG:
            return max(self._eig(campaign), 0.0)
        return 1.0                                # equal (uniform weights)

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

    def _intra_prereqs(self, ids: list[str]) -> dict[str, set[str]]:
        """For each id, the set of its dependencies that are also in ``ids`` — the
        ordering constraints internal to this set. Dependencies outside the set are
        external prerequisites, not edges of this graph. Reuses the single
        dependency-normalisation source (no duplicated dependency logic)."""
        in_set = set(ids)
        prereqs: dict[str, set[str]] = {}
        for cid in ids:
            camp = campaign_store.get_campaign(cid, db_path=self.db_path) or {}
            prereqs[cid] = {
                dep_id for dep_id, _ in campaign_store.normalized_depends_on(camp)
                if dep_id in in_set
            }
        return prereqs

    def _topo_order(self, ordered_ids: list[str]) -> tuple[list[str], list[str]]:
        """Stable, dependency-aware refinement of a policy-ordered id list, with cycle
        rejection. Returns ``(emitted, excluded)``:

        - ``emitted`` — a prerequisite precedes its dependent; policy order is
          preserved otherwise (deterministic Kahn's algorithm seeded by the policy
          order, restarting the scan on each emit to keep it stable);
        - ``excluded`` — the campaigns that can never be emitted because they sit in
          (or transitively depend on) a dependency cycle. §4 forbids cycles, so these
          are rejected from the plan rather than force-ordered. Sorted, deterministic.
        """
        prereqs = self._intra_prereqs(ordered_ids)
        emitted: list[str] = []
        done: set[str] = set()
        remaining = list(ordered_ids)          # already in policy order
        while remaining:
            progressed = False
            for cid in list(remaining):
                if prereqs[cid] <= done:       # all in-set prereqs already emitted
                    emitted.append(cid)
                    done.add(cid)
                    remaining.remove(cid)
                    progressed = True
                    break                      # restart scan → keep policy order stable
            if not progressed:
                break                          # remaining are cyclic / cycle-dependent
        return emitted, sorted(remaining)

    def _unschedulable(self, ids: list[str]) -> list[str]:
        """The campaigns among ``ids`` that cannot be topologically ordered — cycle
        members and anything transitively depending on them. Sorted, deterministic."""
        prereqs = self._intra_prereqs(ids)
        done: set[str] = set()
        remaining = list(ids)
        while remaining:
            progressed = False
            for cid in list(remaining):
                if prereqs[cid] <= done:
                    done.add(cid)
                    remaining.remove(cid)
                    progressed = True
            if not progressed:
                break
        return sorted(remaining)
