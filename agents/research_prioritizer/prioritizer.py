"""
prioritizer.py — Milestone 10 PR-5 ResearchPrioritizer.

Deterministic. No LLM. The ResearchPrioritizer ranks ``pending`` ideas by an
explainable *Research Value* score and enforces an exploration quota. It sits
beside the existing approval queue: it reads ideas + M9/campaign/memory evidence
and returns an ordering; it NEVER executes, schedules, approves, mutates ideas,
or touches the M7 execution path or the M9 learning path. The human approval
gate is preserved — ranking only changes the *order* a human sees, never the
gate itself.

Research Value
--------------
Every ranked idea carries a full :class:`ScoreBreakdown` with five components,
each normalised to ``[0, 1]``, so a ranking is always auditable:

* **Expected Information Gain (EIG)** — how much we expect to *learn*. High when
  the idea targets a context cell with thin/no M9 evidence; ``1/(1+n)`` in the
  number of prior experiments in that (signal, market, universe, bar_type) cell.
* **Novelty** — structural distinctness from the *other candidates* in the same
  ranking batch; ``1/(1+d)`` in the number of sibling ideas sharing the idea's
  (primary signal, market, universe, bar_type) key. Anti-redundancy pressure.
* **Memory Score** — alignment with accumulated research memory: supportive
  findings for the idea's scope raise it, cautionary findings lower it; neutral
  ``0.5`` when memory is silent.
* **Campaign Priority** — the owning campaign's priority weight
  (``goal_spec.priority``); a neutral default for ideas with no campaign.
* **Cost** — an estimated research cost (bar-type construction complexity +
  signal count) folded in as *cheapness* (``1 - normalised_cost``): cheaper
  experiments score higher.

``research_value`` is a fixed weighted sum of the five (weights live on
:class:`PrioritizerConfig` and are normalised), so identical inputs always
produce an identical score and therefore an identical ordering. Ties break on
``idea_id`` so ordering is total and reproducible.

Exploration quota
-----------------
Each idea is bucketed ``explore`` (``EIG`` ≥ ``explore_eig_threshold`` — i.e. a
thinly-tested cell) or ``exploit``. When a cutoff ``top_k`` is supplied, the
prioritizer *reserves* ``ceil(exploration_fraction * top_k)`` of those slots for
the best explore ideas before filling the rest by value. This guarantees that
exploit ideas — however high-scoring — cannot crowd exploration out of the
selected top_k whenever explore candidates exist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.protocol import normalize_bar_type
from agents.storage.db import DB_PATH
from agents.storage import (
    context_store,
    memory_store,
    campaign_store,
)
from agents.idea_generator import approval_queue


class PrioritizerError(RuntimeError):
    """Raised on an invalid prioritizer operation."""


# Per-bar-type research-cost weights. Time bars are the cheapest to construct;
# imbalance bars are the most expensive. Used only to *estimate* relative cost
# for ranking — it never touches the execution/backtest cost model.
_BAR_COST = {
    "time": 1.0,
    "tick": 1.5,
    "volume": 1.6,
    "dollar": 1.6,
    "volume_imbalance": 2.0,
    "dollar_imbalance": 2.0,
}


@dataclass(frozen=True)
class PrioritizerConfig:
    """Tunable, deterministic ranking parameters."""
    # Component weights (normalised internally; need not sum to 1).
    w_eig: float = 0.35
    w_novelty: float = 0.20
    w_memory: float = 0.15
    w_campaign: float = 0.15
    w_cost: float = 0.15

    min_n: int = 2                       # evidence bar shared with M9/strategist
    attribution_method: str = context_store.DEFAULT_ATTRIBUTION
    exploration_fraction: float = 0.34   # default quota when no campaign override
    explore_eig_threshold: float = 0.5   # EIG ≥ this ⇒ "explore" bucket
    max_cost: float = 3.0                # normaliser for the cost estimate
    default_campaign_priority: float = 0.5
    ndigits: int = 6                     # rounding for reproducible scores


@dataclass(frozen=True)
class ScoreBreakdown:
    """The full, explainable decomposition of one idea's Research Value."""
    expected_information_gain: float
    novelty: float
    memory_score: float
    campaign_priority: float
    cost: float                  # cheapness in [0,1] (1 = cheapest)
    research_value: float
    bucket: str                  # "explore" | "exploit"
    cost_estimate: float         # raw estimated cost (pre-normalisation)
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "expected_information_gain": self.expected_information_gain,
            "novelty": self.novelty,
            "memory_score": self.memory_score,
            "campaign_priority": self.campaign_priority,
            "cost": self.cost,
            "research_value": self.research_value,
            "bucket": self.bucket,
            "cost_estimate": self.cost_estimate,
            "evidence": dict(self.evidence),
        }


@dataclass
class RankedIdea:
    """An idea plus its rank and explainable score breakdown."""
    idea: dict[str, Any]
    breakdown: ScoreBreakdown
    rank: int

    @property
    def idea_id(self) -> str:
        return self.idea.get("idea_id", "")

    @property
    def bucket(self) -> str:
        return self.breakdown.bucket

    def as_dict(self) -> dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "rank": self.rank,
            "score_breakdown": self.breakdown.as_dict(),
        }


# Cautionary / supportive keywords for the (deliberately simple, deterministic)
# memory-sentiment read. Semantic dedup of memory is deferred (TD-5).
_NEG_WORDS = ("retire", "avoid", "refut", "does not", "no edge", "weak", "decay")
_POS_WORDS = ("promot", "prioriti", "robust", "generali", "confirm", "strong")


class ResearchPrioritizer:
    """Deterministic, explainable Research Value ranking over pending ideas."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        config: PrioritizerConfig | None = None,
    ):
        self.db_path = db_path
        self.config = config or PrioritizerConfig()

    # ------------------------------------------------------------------ public
    def rank_pending(
        self, *, top_k: int | None = None, campaign_id: str | None = None
    ) -> list[RankedIdea]:
        """Rank the current ``pending`` ideas (optionally one campaign's)."""
        ideas = approval_queue.list_pending(db_path=self.db_path)
        if campaign_id is not None:
            ideas = [i for i in ideas if i.get("campaign_id") == campaign_id]
        return self.rank(ideas, top_k=top_k)

    def rank(
        self,
        ideas: list[dict[str, Any]],
        *,
        top_k: int | None = None,
        exploration_fraction: float | None = None,
    ) -> list[RankedIdea]:
        """Score and order ``ideas`` deterministically with quota enforcement.

        The returned list is a *total* order: every input idea appears exactly
        once. When ``top_k`` is given, the first ``top_k`` entries are guaranteed
        to include ``ceil(frac * top_k)`` explore ideas (when that many exist),
        so exploit ideas cannot crowd exploration out of the selection window.
        """
        if not ideas:
            return []

        # 1. Score every idea (batch-aware: novelty depends on siblings).
        sibling_counts = self._sibling_counts(ideas)
        scored: list[tuple[dict, ScoreBreakdown]] = []
        for idea in ideas:
            scored.append((idea, self._score(idea, sibling_counts)))

        # 2. Deterministic value order; ties break on idea_id.
        def _key(item: tuple[dict, ScoreBreakdown]):
            idea, b = item
            return (-b.research_value, idea.get("idea_id", ""))

        value_order = sorted(scored, key=_key)

        # 3. Enforce the exploration quota over the selection window.
        ordered = self._apply_quota(value_order, top_k, exploration_fraction)

        return [
            RankedIdea(idea=idea, breakdown=b, rank=i)
            for i, (idea, b) in enumerate(ordered)
        ]

    def score_idea(self, idea: dict[str, Any]) -> ScoreBreakdown:
        """Score a single idea in isolation (novelty assumes no siblings)."""
        return self._score(idea, self._sibling_counts([idea]))

    # --------------------------------------------------------------- internals
    def _apply_quota(
        self,
        value_order: list[tuple[dict, ScoreBreakdown]],
        top_k: int | None,
        exploration_fraction: float | None,
    ) -> list[tuple[dict, ScoreBreakdown]]:
        n = len(value_order)
        k = n if top_k is None else max(0, min(top_k, n))
        if k == 0 or k == n:
            # No cutoff (or selecting everything): value order already total and
            # the quota is trivially satisfiable — nothing to reserve.
            return value_order

        frac = (
            self.config.exploration_fraction
            if exploration_fraction is None
            else exploration_fraction
        )
        quota = math.ceil(frac * k)
        explore = [x for x in value_order if x[1].bucket == "explore"]
        reserved = min(quota, len(explore))
        if reserved == 0:
            return value_order

        # Reserve the best `reserved` explore ideas; they are guaranteed a slot
        # inside the top_k window even if their value is lower than exploit ideas.
        reserved_ids = {x[0].get("idea_id", "") for x in explore[:reserved]}

        chosen: list[tuple[dict, ScoreBreakdown]] = [
            x for x in value_order if x[0].get("idea_id", "") in reserved_ids
        ]
        for x in value_order:
            if len(chosen) >= k:
                break
            if x[0].get("idea_id", "") in reserved_ids:
                continue
            chosen.append(x)

        # Order the selected window by value (explainability) and append the
        # remainder in value order. Deterministic throughout.
        chosen_ids = {x[0].get("idea_id", "") for x in chosen}
        chosen.sort(key=lambda item: (-item[1].research_value,
                                      item[0].get("idea_id", "")))
        remainder = [x for x in value_order
                     if x[0].get("idea_id", "") not in chosen_ids]
        return chosen + remainder

    def _score(
        self, idea: dict[str, Any], sibling_counts: dict[tuple, int]
    ) -> ScoreBreakdown:
        cfg = self.config
        sig = self._primary_signal(idea)
        market = idea.get("market") or "unknown"
        universe = idea.get("universe") or "unknown"
        bar_type = normalize_bar_type(idea.get("bar_type"))

        eig, n_prior = self._eig(sig, market, universe, bar_type)
        novelty = self._novelty(idea, sibling_counts)
        memory = self._memory_score(sig, market, universe)
        campaign_priority = self._campaign_priority(idea)
        cost_estimate = self._cost_estimate(idea)
        cheapness = self._round(1.0 - min(1.0, cost_estimate / cfg.max_cost))

        # Normalised weighted blend → research_value in [0,1].
        w = (cfg.w_eig, cfg.w_novelty, cfg.w_memory, cfg.w_campaign, cfg.w_cost)
        wsum = sum(w) or 1.0
        value = (
            cfg.w_eig * eig
            + cfg.w_novelty * novelty
            + cfg.w_memory * memory
            + cfg.w_campaign * campaign_priority
            + cfg.w_cost * cheapness
        ) / wsum

        bucket = "explore" if eig >= cfg.explore_eig_threshold else "exploit"

        return ScoreBreakdown(
            expected_information_gain=self._round(eig),
            novelty=self._round(novelty),
            memory_score=self._round(memory),
            campaign_priority=self._round(campaign_priority),
            cost=cheapness,
            research_value=self._round(value),
            bucket=bucket,
            cost_estimate=self._round(cost_estimate),
            evidence={
                "primary_signal": sig,
                "market": market,
                "universe": universe,
                "bar_type": bar_type,
                "n_prior_experiments": n_prior,
                "siblings": sibling_counts.get(
                    self._sibling_key(idea), 1) - 1,
            },
        )

    # -- component: Expected Information Gain ------------------------------
    def _eig(self, sig, market, universe, bar_type) -> tuple[float, int]:
        """Thin evidence ⇒ high EIG. ``1/(1+n)`` in the target cell's prior
        experiment count (read-only from the M9 context cache)."""
        n_prior = 0
        if sig:
            cells = context_store.context_performance(
                feature_name=sig, market=market, universe=universe,
                bar_type=bar_type,
                attribution_method=self.config.attribution_method,
                db_path=self.db_path,
            )
            if cells:
                n_prior = int(cells[0].get("n_experiments", 0) or 0)
        return 1.0 / (1.0 + n_prior), n_prior

    # -- component: Novelty (batch-structural) ----------------------------
    def _novelty(self, idea, sibling_counts) -> float:
        d = sibling_counts.get(self._sibling_key(idea), 1) - 1  # other siblings
        return 1.0 / (1.0 + max(0, d))

    # -- component: Memory Score ------------------------------------------
    def _memory_score(self, sig, market, universe) -> float:
        """0.5 neutral, nudged up by supportive memory and down by cautionary
        memory whose scope or finding matches the idea's signal/context."""
        rows = memory_store.list_memory(db_path=self.db_path, limit=200)
        score = 0.5
        ctx_prefix = f"{market}/{universe}"
        for r in rows:
            scope = (r.get("scope_key") or "")
            finding = (r.get("finding") or "").lower()
            relevant = (
                (sig and sig.lower() in finding)
                or scope.startswith(ctx_prefix)
            )
            if not relevant:
                continue
            weight = {"high": 0.20, "medium": 0.12, "low": 0.06}.get(
                (r.get("confidence") or "medium").lower(), 0.12)
            if any(wd in finding for wd in _NEG_WORDS):
                score -= weight
            elif any(wd in finding for wd in _POS_WORDS):
                score += weight
        return max(0.0, min(1.0, score))

    # -- component: Campaign Priority -------------------------------------
    def _campaign_priority(self, idea) -> float:
        cid = idea.get("campaign_id")
        if not cid:
            return self.config.default_campaign_priority
        campaign = campaign_store.get_campaign(cid, db_path=self.db_path)
        if not campaign:
            return self.config.default_campaign_priority
        goal = campaign.get("goal_spec") or {}
        if isinstance(goal, dict) and goal.get("priority") is not None:
            try:
                return max(0.0, min(1.0, float(goal["priority"])))
            except (TypeError, ValueError):
                pass
        return self.config.default_campaign_priority

    # -- component: Cost estimate -----------------------------------------
    def _cost_estimate(self, idea) -> float:
        bar_type = normalize_bar_type(idea.get("bar_type"))
        base = _BAR_COST.get(bar_type, 1.0)
        sigs = self._signals(idea)
        return base + 0.25 * max(0, len(sigs) - 1)

    # -- shared helpers ---------------------------------------------------
    def _sibling_counts(self, ideas) -> dict[tuple, int]:
        counts: dict[tuple, int] = {}
        for idea in ideas:
            key = self._sibling_key(idea)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _sibling_key(self, idea) -> tuple:
        return (
            self._primary_signal(idea) or "",
            idea.get("market") or "unknown",
            idea.get("universe") or "unknown",
            normalize_bar_type(idea.get("bar_type")),
        )

    @staticmethod
    def _signals(idea) -> list[str]:
        sigs = idea.get("suggested_signals")
        if sigs is None:
            return []
        if isinstance(sigs, str):
            return [sigs] if sigs else []
        return list(sigs)

    @classmethod
    def _primary_signal(cls, idea) -> str | None:
        sigs = cls._signals(idea)
        return sigs[0] if sigs else None

    def _round(self, x: float) -> float:
        return round(float(x), self.config.ndigits)
