"""
decision.py — the pure ``decision_v1`` consumption policy (M11 PR-8).

The **decision-consumption** layer: it turns the M11 evidence projections
(posterior axes + stage + retirement) into the boolean signals the existing
research agents already reason with — *confirmed*, *refuted*, *generalises* — so an
agent can consume statistical evidence instead of the coarse M9 heuristic.

Pure: no database, no RNG, no wall-clock. It operates on an :class:`EvidenceView`
that the caller loads from the M11 stores. When no view exists for a node (no
posterior yet), the caller falls back to its existing heuristic — so the old path
is recovered exactly when evidence is absent (back-compat).

Bars are aligned with the sibling engines so all actors agree on the evidence
threshold: ``confirm_pi`` = Promotion's Promising π≥0.90; ``refute_pi`` =
Retirement's ε_ref (0.05); ``generalise_g_count`` = Validated's G_cnt≥2.
"""

from __future__ import annotations

from dataclasses import dataclass

RETIRED_REFUTED = "Retired-Refuted"


@dataclass(frozen=True)
class DecisionPolicy:
    version: str = "decision_v1"
    S0: float = 0.0
    confirm_pi: float = 0.90           # π_h bar for "confirmed" (== Promising)
    refute_pi: float = 0.05            # π_h bar for "refuted" (== ε_ref)
    generalise_g_count: int = 2        # cells clearing the bar (== Validated G_cnt)


DEFAULT_POLICY = DecisionPolicy()


@dataclass(frozen=True)
class EvidenceView:
    """The M11 signals consumed for one hypothesis/node (loaded by the caller)."""
    hypothesis_id: str
    q_exceed_prob: float          # π_h = Pr(θ_h > S0)
    posterior_mean: float         # μ_h
    g_count: int                  # G-axis: cells clearing the bar
    retired: bool                 # retirement_evaluation.retired
    retired_state: str | None     # e.g. 'Retired-Refuted' (None when live)


def is_confirmed(view: EvidenceView, policy: DecisionPolicy = DEFAULT_POLICY) -> bool:
    """A real, positive edge by the posterior — and not retired."""
    if view.retired:
        return False
    return view.q_exceed_prob >= policy.confirm_pi and view.posterior_mean > policy.S0


def is_refuted(view: EvidenceView, policy: DecisionPolicy = DEFAULT_POLICY) -> bool:
    """The edge is affirmatively absent: Retired-Refuted, or π below the floor."""
    if view.retired_state == RETIRED_REFUTED:
        return True
    return view.q_exceed_prob <= policy.refute_pi


def does_generalise(view: EvidenceView, policy: DecisionPolicy = DEFAULT_POLICY) -> bool:
    """Survives across enough context cells (G axis)."""
    return view.g_count >= policy.generalise_g_count
