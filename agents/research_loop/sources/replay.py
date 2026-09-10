"""
counterfactual_replay source — Phase 6 P6-5.

A thin, deterministic proposer that re-runs prior/abandoned experiment specs under
new conditions (new bar types). Each proposal is a **new** append-only ``pending``
idea (a fresh idea_id → a fresh experiment_id downstream); original experiments are
never mutated — the replay reuses the whole pipeline (design §10).

Registers itself via ``@register`` — the loop is never touched.

``scope`` shape::

    {"replay": [
        {"hypothesis": str, "signals": [...], "market": str, "universe": str,
         "bar_types": ["volume", "dollar"]}   # target clocks for THIS spec
      ],
     "bar_types": ["volume", ...]}            # optional fallback target clocks

Determinism: specs are replayed in listed order × sorted target bar types;
already-proposed ``(bar_type, hypothesis)`` pairs are skipped, so the source
converges and re-ticking proposes nothing new. Auto-sourcing prior specs from the
ledger (the full replay "body") is a future extension; this source takes the specs
to replay from the campaign scope, keeping it thin and fully deterministic.
"""

from __future__ import annotations

from typing import Any

from agents.protocol import SUPPORTED_BAR_TYPES, normalize_bar_type
from agents.research_loop.sources import (
    CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY,
    HypothesisSource,
    Proposal,
    SourceContext,
    campaign_scope,
    enqueue_proposal,
    existing_specs,
    register,
)

_ORIGIN = CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY


class CounterfactualReplaySource:
    def __init__(self, context: SourceContext) -> None:
        self._ctx = context

    def propose(self, campaign_id: str) -> list[Proposal]:
        scope = campaign_scope(self._ctx, campaign_id)
        specs = scope.get("replay") or []
        if not specs:
            return []  # nothing to replay — safe no-op
        fallback = scope.get("bar_types") or SUPPORTED_BAR_TYPES
        already = existing_specs(self._ctx, campaign_id)
        out: list[Proposal] = []
        for spec in specs:
            hypothesis = spec.get("hypothesis")
            if not hypothesis:
                continue
            targets = sorted(
                {normalize_bar_type(b) for b in (spec.get("bar_types") or fallback)}
            )
            for bar_type in targets:
                if (bar_type, hypothesis) in already:
                    continue
                out.append(enqueue_proposal(
                    self._ctx, campaign_id,
                    hypothesis=hypothesis,
                    signals=list(spec.get("signals") or []),
                    market=spec.get("market", ""),
                    universe=spec.get("universe", ""),
                    bar_type=bar_type,
                    rationale=f"counterfactual replay under bar_type={bar_type}",
                    origin=_ORIGIN,
                ))
        return out


@register(CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY)
def _make(context: SourceContext) -> HypothesisSource:
    return CounterfactualReplaySource(context)
