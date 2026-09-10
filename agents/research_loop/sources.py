"""
HypothesisSource registry — Phase 6 P6-2.

A campaign's ``campaign_type`` selects a **HypothesisSource** that proposes WHAT
research to perform for a tick; the existing agents (Designer, executor, M11)
decide HOW. The registry is a plain data-driven mapping — future campaign types
(``bar_type_comparison``, ``overlay_combination``, ``counterfactual_replay``,
``literature_review``, ``github_mining``, …) plug in by registering a source; the
loop, engines, and scheduler are untouched.

This module holds no research intelligence and is not an agent: a source is a thin
adapter over existing capability. Sources must be **deterministic** — identical
stored state ⇒ identical proposals — so the loop stays replayable.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# The only campaign type wired in P6-2. Others are registered by later PRs.
CAMPAIGN_TYPE_STRATEGY_EVOLUTION = "strategy_evolution"
DEFAULT_CAMPAIGN_TYPE = CAMPAIGN_TYPE_STRATEGY_EVOLUTION


@runtime_checkable
class HypothesisSource(Protocol):
    """Proposes new hypotheses/ideas for a campaign tick (WHAT to research)."""

    def propose(self, campaign_id: str) -> list[Any]:
        ...


class StrategistSource:
    """Default source: the ResearchStrategist frontier expansion.

    Wraps the loop's existing strategist so ``strategy_evolution`` is byte-identical
    to the pre-Phase-6 generate phase — the source is a pass-through, adding no new
    behaviour.
    """

    def __init__(self, strategist: Any) -> None:
        self._strategist = strategist

    def propose(self, campaign_id: str) -> list[Any]:
        return self._strategist.run_tick(campaign_id)


def default_registry(strategist: Any) -> dict[str, HypothesisSource]:
    """The built-in registry. P6-2 wires only ``strategy_evolution``; future PRs
    add entries here (or the loop merges injected sources over this default)."""
    return {CAMPAIGN_TYPE_STRATEGY_EVOLUTION: StrategistSource(strategist)}
