"""
overlay_combination source — Phase 6 P6-5.

A thin, deterministic enumerator: for a base spec in ``scope``, propose one
``pending`` idea per combination of overlays (up to ``scope.max_overlay_combo``).
The overlay combo is recorded in the idea's hypothesis/rationale text; applying the
overlay is the downstream Designer's job — this source only enumerates WHAT to try.

Registers itself via ``@register`` — the loop is never touched.

``scope`` shape::

    {"base": {"hypothesis": str, "signals": [...], "market": str,
              "universe": str, "bar_type": str},   # bar_type optional
     "overlays": ["vol_filter", "regime_gate", ...],
     "max_overlay_combo": 1}                        # optional, default 1

Determinism: combinations are generated in sorted order (by size, then members);
already-proposed ``(bar_type, hypothesis)`` pairs are skipped, so the source
converges and re-ticking proposes nothing new.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

from agents.research_loop.sources import (
    CAMPAIGN_TYPE_OVERLAY_COMBINATION,
    HypothesisSource,
    Proposal,
    SourceContext,
    campaign_scope,
    enqueue_proposal,
    existing_specs,
    register,
)

_ORIGIN = CAMPAIGN_TYPE_OVERLAY_COMBINATION


def _combos(overlays: list[str], max_size: int) -> list[tuple[str, ...]]:
    """All non-empty overlay combinations up to ``max_size``, in a total order
    (by size, then lexicographic on the sorted members)."""
    uniq = sorted(set(overlays))
    out: list[tuple[str, ...]] = []
    for size in range(1, max(0, max_size) + 1):
        out.extend(combinations(uniq, size))
    return out


class OverlayCombinationSource:
    def __init__(self, context: SourceContext) -> None:
        self._ctx = context

    def propose(self, campaign_id: str) -> list[Proposal]:
        scope = campaign_scope(self._ctx, campaign_id)
        base = scope.get("base") or {}
        base_hyp = base.get("hypothesis")
        overlays = scope.get("overlays") or []
        if not base_hyp or not overlays:
            return []  # nothing to combine — safe no-op
        max_combo = int(scope.get("max_overlay_combo", 1))
        bar_type = base.get("bar_type", "time")
        already = existing_specs(self._ctx, campaign_id)
        out: list[Proposal] = []
        for combo in _combos(list(overlays), max_combo):
            hypothesis = f"{base_hyp} | overlays={'+'.join(combo)}"
            if (bar_type, hypothesis) in already:
                continue
            out.append(enqueue_proposal(
                self._ctx, campaign_id,
                hypothesis=hypothesis,
                signals=list(base.get("signals") or []),
                market=base.get("market", ""),
                universe=base.get("universe", ""),
                bar_type=bar_type,
                rationale=f"overlay combination: {'+'.join(combo)}",
                origin=_ORIGIN,
            ))
        return out


@register(CAMPAIGN_TYPE_OVERLAY_COMBINATION)
def _make(context: SourceContext) -> HypothesisSource:
    return OverlayCombinationSource(context)
