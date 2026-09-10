"""
bar_type_comparison source — Phase 6 P6-5.

A thin, deterministic sweep: for a base spec declared in the campaign's ``scope``,
propose one ``pending`` idea per bar type in ``scope.bar_types`` (defaulting to all
supported clocks). This is the "does the edge survive a change of sampling clock?"
campaign — pure enumeration, no research intelligence.

Registers itself via ``@register`` — the loop is never touched.

``scope`` shape::

    {"base": {"hypothesis": str, "signals": [str, ...],
              "market": str, "universe": str},
     "bar_types": ["time", "volume", ...]}   # optional; defaults to all supported

Determinism: bar types are swept in sorted order; already-proposed
``(bar_type, hypothesis)`` pairs are skipped, so the source converges (proposes each
clock once) and re-ticking the same state proposes nothing new.
"""

from __future__ import annotations

from typing import Any

from agents.protocol import SUPPORTED_BAR_TYPES, normalize_bar_type
from agents.research_loop.sources import (
    CAMPAIGN_TYPE_BAR_TYPE_COMPARISON,
    HypothesisSource,
    Proposal,
    SourceContext,
    campaign_scope,
    enqueue_proposal,
    existing_specs,
    register,
)

_ORIGIN = CAMPAIGN_TYPE_BAR_TYPE_COMPARISON


class BarTypeComparisonSource:
    def __init__(self, context: SourceContext) -> None:
        self._ctx = context

    def propose(self, campaign_id: str) -> list[Proposal]:
        scope = campaign_scope(self._ctx, campaign_id)
        base = scope.get("base") or {}
        hypothesis = base.get("hypothesis")
        if not hypothesis:
            return []  # nothing to sweep — safe no-op
        bar_types = sorted(
            {normalize_bar_type(b) for b in (scope.get("bar_types") or SUPPORTED_BAR_TYPES)}
        )
        already = existing_specs(self._ctx, campaign_id)
        out: list[Proposal] = []
        for bar_type in bar_types:
            if (bar_type, hypothesis) in already:
                continue
            out.append(enqueue_proposal(
                self._ctx, campaign_id,
                hypothesis=hypothesis,
                signals=list(base.get("signals") or []),
                market=base.get("market", ""),
                universe=base.get("universe", ""),
                bar_type=bar_type,
                rationale=f"bar-type sweep: {bar_type}",
                origin=_ORIGIN,
            ))
        return out


@register(CAMPAIGN_TYPE_BAR_TYPE_COMPARISON)
def _make(context: SourceContext) -> HypothesisSource:
    return BarTypeComparisonSource(context)
