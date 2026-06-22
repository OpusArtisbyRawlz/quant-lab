"""
quota.py — Milestone 10 PR-8 exploration quota + anti-mode-collapse planner.

Deterministic. No LLM. No I/O. The :class:`ExplorationPlanner` is a pure
function of its inputs: given an ordered list of candidate ideas (each already
classified ``explore`` / ``exploit`` and tagged with a context key), it selects
a bounded *dispatch window* that:

  1. **Respects an exploration quota** — at least ``ceil(frac * window)`` of the
     selected slots are reserved for the best ``explore`` candidates whenever
     that many exist, so high-value ``exploit`` candidates can NEVER consume
     every slot (anti-mode-collapse guarantee #1).
  2. **Enforces context diversity** — no more than ``max_per_context`` selected
     ideas may share the same M9 context key
     (``signal × market × universe × bar_type``), so a single context cannot
     dominate a tick (anti-mode-collapse guarantee #2).
  3. **Honours an external admission predicate** — an optional ``accept``
     callback is consulted (and its side effects, e.g. per-campaign budget
     consumption, applied) only at the moment a candidate is actually selected.

The planner does NOT score, rank, approve, schedule, or execute anything: it
only *selects and orders* from a pre-ranked candidate stream. Determinism: the
incoming candidate order is treated as the authoritative value order; selection
never re-sorts by raw score, so identical inputs always yield identical output
(ties were already broken upstream by the prioritizer's ``idea_id`` tiebreak).

This module is the seam that PR-8 wires into the ResearchScheduler's dispatch
plan; it carries no storage dependency so it is trivially unit-testable and
reusable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable

# Candidate buckets (mirrors the prioritizer's ScoreBreakdown.bucket vocabulary).
BUCKET_EXPLORE = "explore"
BUCKET_EXPLOIT = "exploit"


@dataclass(frozen=True)
class QuotaConfig:
    """Tunable, deterministic quota / diversity parameters."""

    # Fraction of the dispatch window reserved for explore candidates.
    exploration_fraction: float = 0.34
    # Max selected ideas that may share one context key in a single window.
    # None ⇒ context diversity is not enforced.
    max_per_context: int | None = 2


@dataclass(frozen=True)
class Candidate:
    """One rankable dispatch candidate. Pure data.

    ``order`` is the candidate's position in the upstream value ranking (lower =
    higher value); it is the *only* thing used to order selection, so the planner
    inherits the prioritizer's determinism.
    """

    idea_id: str
    bucket: str                       # BUCKET_EXPLORE | BUCKET_EXPLOIT
    context_key: Hashable             # (signal, market, universe, bar_type)
    order: int                        # 0-based rank in the incoming value order
    campaign_id: str | None = None
    research_value: float | None = None
    payload: Any = None               # opaque carry-through (e.g. the RankedIdea)

    @property
    def is_explore(self) -> bool:
        return self.bucket == BUCKET_EXPLORE


@dataclass
class QuotaPlan:
    """The selected dispatch window plus a full, auditable accounting."""

    selected: list[Candidate] = field(default_factory=list)
    window: int = 0
    quota_target: int = 0             # reserved explore slots requested
    explore_selected: list[str] = field(default_factory=list)
    exploit_selected: list[str] = field(default_factory=list)
    dropped_for_context: list[str] = field(default_factory=list)
    dropped_for_admission: list[str] = field(default_factory=list)

    @property
    def explore_count(self) -> int:
        return len(self.explore_selected)

    @property
    def exploit_count(self) -> int:
        return len(self.exploit_selected)

    @property
    def quota_met(self) -> bool:
        """True iff the reserved quota was filled (or there were too few explore
        candidates to fill it — in which case the quota is vacuously satisfied)."""
        return self.explore_count >= self.quota_target

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": [c.idea_id for c in self.selected],
            "window": self.window,
            "quota_target": self.quota_target,
            "explore_selected": list(self.explore_selected),
            "exploit_selected": list(self.exploit_selected),
            "dropped_for_context": list(self.dropped_for_context),
            "dropped_for_admission": list(self.dropped_for_admission),
            "explore_count": self.explore_count,
            "exploit_count": self.exploit_count,
            "quota_met": self.quota_met,
        }


# Predicate consulted at selection time; returning False rejects the candidate
# AND must not apply any side effect (e.g. budget is only consumed on True).
AdmitFn = Callable[[Candidate], bool]


class ExplorationPlanner:
    """Deterministic exploration-quota + context-diversity window selector."""

    def __init__(self, config: QuotaConfig | None = None) -> None:
        self.config = config or QuotaConfig()

    def plan(
        self,
        candidates: list[Candidate],
        window: int,
        *,
        exploration_fraction: float | None = None,
        accept: AdmitFn | None = None,
    ) -> QuotaPlan:
        """Select up to ``window`` candidates honouring quota + diversity.

        ``candidates`` MUST already be in descending value order (the planner
        trusts and preserves that order). ``window`` is the maximum number of
        ideas to select (e.g. the dispatch cap minus retries already planned).
        ``accept`` — if given — is the final admission gate for each selected
        candidate; its side effects fire only when it returns True.
        """
        k = max(0, int(window))
        frac = (
            self.config.exploration_fraction
            if exploration_fraction is None
            else exploration_fraction
        )
        frac = min(1.0, max(0.0, float(frac)))
        plan = QuotaPlan(window=k, quota_target=math.ceil(frac * k) if k else 0)
        if k == 0 or not candidates:
            return plan

        # Stable copy in incoming (value) order; we never re-sort by raw score.
        ordered = sorted(candidates, key=lambda c: (c.order, c.idea_id))
        max_ctx = self.config.max_per_context

        chosen_ids: set[str] = set()
        ctx_count: dict[Hashable, int] = {}

        def _try_select(c: Candidate) -> bool:
            if len(plan.selected) >= k or c.idea_id in chosen_ids:
                return False
            if max_ctx is not None and ctx_count.get(c.context_key, 0) >= max_ctx:
                if c.idea_id not in plan.dropped_for_context:
                    plan.dropped_for_context.append(c.idea_id)
                return False
            if accept is not None and not accept(c):
                if c.idea_id not in plan.dropped_for_admission:
                    plan.dropped_for_admission.append(c.idea_id)
                return False
            chosen_ids.add(c.idea_id)
            ctx_count[c.context_key] = ctx_count.get(c.context_key, 0) + 1
            plan.selected.append(c)
            return True

        # Pass 1 — reserve the quota for the best explore candidates. This is the
        # anti-mode-collapse guarantee: it runs BEFORE exploit ideas are allowed
        # to fill the window, so exploit ideas can never crowd exploration out.
        reserved = 0
        if plan.quota_target > 0:
            for c in ordered:
                if reserved >= plan.quota_target or len(plan.selected) >= k:
                    break
                if c.is_explore and _try_select(c):
                    reserved += 1

        # Pass 2 — fill the rest of the window in value order (either bucket).
        for c in ordered:
            if len(plan.selected) >= k:
                break
            _try_select(c)

        # Final order: value order (stable), so the selection stays explainable.
        plan.selected.sort(key=lambda c: (c.order, c.idea_id))
        plan.explore_selected = [c.idea_id for c in plan.selected if c.is_explore]
        plan.exploit_selected = [
            c.idea_id for c in plan.selected if not c.is_explore
        ]
        return plan
