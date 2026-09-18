"""
historical_recovery source — Historical Strategy Recovery.

A thin, deterministic HypothesisSource that re-proposes the historical strategies of
Projects 03-06 from the curated manifest (`agents.recovery`). It self-registers via
``@register`` — the loop is never touched — and, like every P6-5 source, only
*enumerates* candidates and enqueues them as ``pending`` ideas through the existing
approval path (the human gate is intact). It holds no research intelligence: the
"what to recover" is the operator-reviewed manifest; the "how" is the existing
Designer/executor pipeline.

Campaign ``scope`` controls the selection:
  - ``recovery_kind``: 'baseline' (default) | 'blend' | 'overlay' | 'deployment' | 'all'
  - ``strategy_ids``:  optional explicit subset (overrides recovery_kind)
  - ``bar_types``:     optional list; when it has >1 clock this is the Alternative Bar
                       sweep — each alt-bar-eligible strategy is proposed once per clock.
                       Absent ⇒ each strategy is proposed at its own manifest bar_type.

Determinism: strategies are enumerated in sorted manifest order, bar types sorted, and
already-proposed ``(bar_type, hypothesis)`` pairs are skipped, so the source converges
(each candidate once) and re-ticking the same state proposes nothing new.
"""

from __future__ import annotations

from typing import Any

from agents.protocol import normalize_bar_type
from agents import recovery
from agents.research_loop.sources import (
    HypothesisSource,
    Proposal,
    SourceContext,
    campaign_scope,
    enqueue_proposal,
    existing_specs,
    register,
)

CAMPAIGN_TYPE_HISTORICAL_RECOVERY = "historical_recovery"
_ORIGIN = CAMPAIGN_TYPE_HISTORICAL_RECOVERY


def _selected(scope: dict[str, Any]) -> list[dict[str, Any]]:
    """The manifest strategies this campaign should recover, per scope. Deterministic
    (manifest enumeration is sorted by strategy_id)."""
    ids = scope.get("strategy_ids")
    if ids:
        wanted = set(ids)
        return [s for s in recovery.enumerate_strategies() if s["strategy_id"] in wanted]
    kind = scope.get("recovery_kind", recovery.KIND_BASELINE)
    if kind == "all":
        return recovery.enumerate_strategies()
    return recovery.strategies_for_kind(kind)


class HistoricalRecoverySource:
    def __init__(self, context: SourceContext) -> None:
        self._ctx = context

    def propose(self, campaign_id: str) -> list[Proposal]:
        scope = campaign_scope(self._ctx, campaign_id)
        strategies = _selected(scope)
        if not strategies:
            return []
        sweep = scope.get("bar_types")
        sweep_clocks = sorted({normalize_bar_type(b) for b in sweep}) if sweep else None
        already = existing_specs(self._ctx, campaign_id)

        out: list[Proposal] = []
        for s in strategies:
            hypothesis = s["hypothesis"]
            # Alt-bar sweep applies only to strategies flagged eligible; others (and
            # the no-sweep case) use the strategy's own manifest bar_type.
            if sweep_clocks and s.get("alt_bar_eligible"):
                clocks = sweep_clocks
            else:
                clocks = [normalize_bar_type(s["bar_type"])]
            for bar_type in clocks:
                if (bar_type, hypothesis) in already:
                    continue
                out.append(enqueue_proposal(
                    self._ctx, campaign_id,
                    hypothesis=hypothesis,
                    signals=list(s["signals"]),
                    market=s.get("market", ""),
                    universe=s.get("universe", ""),
                    bar_type=bar_type,
                    rationale=f"recover {s['strategy_id']} from {s['project']}"
                              + (f" @ {bar_type} bars" if sweep_clocks else ""),
                    origin=_ORIGIN,
                ))
        return out


@register(CAMPAIGN_TYPE_HISTORICAL_RECOVERY)
def _make(context: SourceContext) -> HypothesisSource:
    return HistoricalRecoverySource(context)
