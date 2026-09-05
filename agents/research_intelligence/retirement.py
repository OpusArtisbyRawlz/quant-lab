"""
retirement.py — the pure ``retirement_v1`` policy (M11 PR-6), methodology §3.2.

Retirement is a first-class lifecycle track: a hypothesis enters a terminal
retired state when its posterior makes continued investment unjustified. These are
positive conclusions the system draws, not "failures to promote".

This module is pure: no database, no RNG, no wall-clock. It **consumes the
existing posterior** (π_h, CI_high from PR-2 ``hypothesis_state``) and recomputes
no statistics. Retirement is evaluated as a **stateless function of the current
posterior**, so it is replay-deterministic and "reopens" automatically: if new
evidence lifts the posterior back above the predicate, the next rebuild returns
``Live`` (§3.2 reopen-on-new-evidence, reproducible and auditable).

## Scope (PR-6)

Only **Retired-Refuted** — the sole §3.2 state whose predicate and constants are
fully pinned by §10 and derivable from the current posterior — is *fired*:

    Retired-Refuted ⇔ Pr(θ_h > S0) ≤ ε_ref (0.05)  AND  CI_high_h < S★ (0.5)

The other three states are **modelled but deferred** (recognized lifecycle values
this policy never assigns yet), each blocked on a subsystem that does not exist:

  * Retired-Decayed   — needs platform-wide event-time decay in the posterior
                        (the current clock is per-hypothesis, so n_eff/π never
                        fade from staleness); a posterior revision, out of scope.
  * Retired-Saturated — needs EVOI (§4 evidence budget), not yet built.
  * Retired-Redundant — needs a hypothesis novelty/similarity subsystem, not built.

Retirement writes no promotion decision and freezes no budget here (budget is §4);
the two lifecycle tracks are composed downstream by the orchestrating agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Lifecycle states (retirement track)
# ---------------------------------------------------------------------------

LIVE = "Live"
RETIRED_REFUTED = "Retired-Refuted"
RETIRED_SATURATED = "Retired-Saturated"
RETIRED_REDUNDANT = "Retired-Redundant"
RETIRED_DECAYED = "Retired-Decayed"

# States recognized by the schema/state-machine but not fired in PR-6, with the
# reason each is blocked. Kept here so the projection can report them explicitly.
DEFERRED_STATES: dict[str, str] = {
    RETIRED_DECAYED: "needs platform-wide event-time decay in the posterior (§6)",
    RETIRED_SATURATED: "needs EVOI / evidence budget (§4)",
    RETIRED_REDUNDANT: "needs a hypothesis novelty/similarity subsystem",
}


@dataclass(frozen=True)
class RetirementPolicy:
    version: str = "retirement_v1"
    S0: float = 0.0             # break-even (null effect)
    S_star: float = 0.5        # economic Sharpe bar (§10)
    epsilon_ref: float = 0.05  # refutation probability (§10)


DEFAULT_POLICY = RetirementPolicy()


# ---------------------------------------------------------------------------
# Inputs / result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetirementInputs:
    """The posterior quantities the retirement policy reads for one hypothesis.

    All consumed verbatim from PR-2 ``hypothesis_state`` — nothing recomputed.
    ``posterior_sd`` / ``n_eff`` are carried only as an audit snapshot (and for
    the deferred states' future use); the Refuted predicate uses just
    ``q_exceed_prob`` (π_h) and ``ci_high``.
    """
    hypothesis_id: str
    q_exceed_prob: float       # π_h = Pr(θ_h > S0)
    ci_high: float             # CI_high_h
    posterior_sd: float | None = None
    n_eff: float | None = None


@dataclass(frozen=True)
class RetirementResult:
    hypothesis_id: str
    retired: bool
    state: str
    reason: str | None
    refuted: bool
    method: str

    def detail(self) -> dict[str, Any]:
        """Serialisable audit trail: the fired predicate + the deferred states."""
        return {
            "refuted": self.refuted,
            "state": self.state,
            "reason": self.reason,
            "deferred": dict(DEFERRED_STATES),
        }


# ---------------------------------------------------------------------------
# The pure policy
# ---------------------------------------------------------------------------

def evaluate_retirement(
    x: RetirementInputs, policy: RetirementPolicy = DEFAULT_POLICY,
) -> RetirementResult:
    """Stateless §3.2 retirement determination from the current posterior.

    Fires **Retired-Refuted** iff the posterior mass sits below break-even
    (π_h ≤ ε_ref) *and* even the upper credible bound is below the economic bar
    (CI_high < S★) — the edge is affirmatively absent, not merely unproven. All
    other states are deferred (see module docstring). Deterministic; no RNG.
    """
    refuted = (x.q_exceed_prob <= policy.epsilon_ref) and (x.ci_high < policy.S_star)
    if refuted:
        return RetirementResult(
            hypothesis_id=x.hypothesis_id,
            retired=True,
            state=RETIRED_REFUTED,
            reason=(f"posterior below break-even: pi<={policy.epsilon_ref} "
                    f"and ci_high<S*({policy.S_star})"),
            refuted=True,
            method=policy.version,
        )
    return RetirementResult(
        hypothesis_id=x.hypothesis_id,
        retired=False,
        state=LIVE,
        reason=None,
        refuted=False,
        method=policy.version,
    )
