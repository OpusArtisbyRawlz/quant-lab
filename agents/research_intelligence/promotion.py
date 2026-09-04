"""
promotion.py — the pure ``promotion_v1`` policy (M11 PR-3).

This module turns a hypothesis's **already-computed** Bayesian posterior and four
evidence axes (produced by the ``stat_v1`` engine in PR-2) into a deterministic
**lifecycle recommendation**. It is a pure decision policy: it recomputes no
statistics, touches no database, and uses no RNG or wall-clock. Given the same
inputs it always returns the same recommendation.

Faithful to ``docs/M11_STATISTICAL_METHODOLOGY.md`` §3.1 (promotion predicates)
and ``docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md`` §6:

  * Promotion is an **AND of per-axis gates** — never a weighted sum of the axes.
    Each gate reads Q, R, G, V (and their sub-components) *independently*, so a
    strong V can never paper over a weak R.
  * The recommendation is the **highest ladder tier whose gates all pass**, walked
    contiguously from Candidate upward.

Scope boundaries fixed for PR-3 (see the PR-3 design doc):

  * **Recommendation only.** Nothing is auto-promoted; this policy returns a
    recommended stage, it does not mutate any hypothesis's authoritative stage.
  * **Cap at Validated.** The Production-Candidate gate additionally mandates a
    holdout pass (§5) and a Benjamini–Hochberg FDR ``q_h ≤ 0.05`` (§7.2). Neither
    subsystem exists yet, so those two inputs are *unavailable*; a mandatory gate
    input that is unavailable is treated as **not satisfied** (conservative — it
    can only ever hold a hypothesis back, never over-promote it). In practice the
    engine therefore recommends at most **Validated** until those PRs land. No
    threshold is invented and no spec-mandated gate is bypassed.
  * **Archived is never auto-derived.** Archived means "reached Production
    Candidate *and accepted/superseded downstream*" — a downstream signal, not a
    posterior predicate. It is a modelled lifecycle value but this pure policy
    never assigns it.
  * **Hysteresis is out of scope here.** §3.1's demotion band applies to a
    *maintained* authoritative stage; this policy computes the upward-gate
    attainable stage from a posterior snapshot and holds no prior stage to demote
    from. The hysteretic transition applier belongs to the loop-integrated assess
    phase (a later slice) and is deliberately not built here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The ``robustness_flags`` vocabulary produced upstream by
# ``agents/experiment_runner/robustness.py``. The frozen methodology says the
# Validated gate requires "no unresolved critical robustness_flag" but does not
# enumerate which flags are critical, so — conservatively — every currently
# defined robustness flag is treated as promotion-blocking until resolved. This
# is a documented ``PromotionPolicy`` knob, not an invented threshold.
FLAG_SUBPERIOD_INSTABILITY = "subperiod_instability"
FLAG_PARAMETER_FRAGILITY = "parameter_fragility"
FLAG_COST_FRAGILITY = "cost_fragility"


# ---------------------------------------------------------------------------
# Lifecycle states (promotion track)
# ---------------------------------------------------------------------------

CANDIDATE = "Candidate"
PROMISING = "Promising"
VALIDATED = "Validated"
PRODUCTION_CANDIDATE = "Production Candidate"
ARCHIVED = "Archived"

# Ordinal ladder. Archived is a modelled terminal-success value but is never
# auto-derived from a posterior (it needs a downstream acceptance signal), so it
# is excluded from the ascending promotion ladder this policy walks.
PROMOTION_LADDER: tuple[str, ...] = (
    CANDIDATE, PROMISING, VALIDATED, PRODUCTION_CANDIDATE,
)
_TIER_INDEX: dict[str, int] = {s: i for i, s in enumerate(PROMOTION_LADDER)}
_TIER_INDEX[ARCHIVED] = len(PROMOTION_LADDER)  # ordinal only; never recommended


def tier_of(stage: str) -> int:
    """Ordinal ladder position of a lifecycle state."""
    return _TIER_INDEX[stage]


# ---------------------------------------------------------------------------
# Policy — every §3.1 / §10 gate constant, versioned ``promotion_v1``
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromotionPolicy:
    version: str = "promotion_v1"

    # Effect-space anchors (§10).
    S0: float = 0.0          # break-even Sharpe (null effect)
    S_star: float = 0.5      # economic Sharpe bar (V / holdout floor)
    k_min: int = 3           # minimum independent replicas

    # Promising gate (§3.1).
    pi_promising: float = 0.90
    prec_promising: float = 0.30
    n_eff_promising: float = 2.0

    # Validated gate (§3.1).
    pi_validated: float = 0.95
    prec_validated: float = 0.60
    rho_sign_validated: float = 0.80
    rho_disp_validated: float = 0.60
    g_count_validated: int = 2

    # Production-Candidate gate (§3.1). q_max and the holdout requirement need
    # subsystems not yet implemented (§7.2 / §5); see module docstring.
    pi_prodc: float = 0.975
    q_max: float = 0.05
    rcnt_prodc: float = 0.75
    g_count_prodc: int = 3
    g_cov_prodc: float = 0.50

    # Robustness flags that block Validated while unresolved.
    critical_robustness_flags: frozenset[str] = frozenset({
        FLAG_SUBPERIOD_INSTABILITY,
        FLAG_PARAMETER_FRAGILITY,
        FLAG_COST_FRAGILITY,
    })


DEFAULT_POLICY = PromotionPolicy()


# ---------------------------------------------------------------------------
# Inputs — the consumed PR-1 evidence + PR-2 posterior for one hypothesis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromotionInputs:
    """Everything the promotion policy reads for one hypothesis.

    All statistical quantities are *consumed* from PR-2's ``hypothesis_state``
    projection; ``replica_count`` and ``has_unresolved_critical_flag`` are cheap
    provenance reads from the PR-1 ``evidence_event`` log. ``q_value`` and
    ``holdout_pass`` are ``None`` in PR-3 because the FDR (§7.2) and holdout (§5)
    subsystems do not exist yet.
    """
    hypothesis_id: str
    # Posterior (point estimate + uncertainty).
    posterior_mean: float
    posterior_sd: float
    ci_low: float
    ci_high: float
    n_eff: float
    # Q — statistical quality.
    q_exceed_prob: float          # π_h
    q_precision: float            # prec_h
    # R — reproducibility.
    r_sign: float                 # ρ^sign
    r_disp: float                 # ρ^disp
    r_replicas: float             # R^cnt
    replica_count: int            # m_h (distinct experiments), from the log
    # G — generalisation.
    g_count: int
    g_coverage: float
    # V — economic value.
    v_net_sharpe: float           # μ_h^net (== posterior_mean under stat_v1)
    v_ci_low: float
    v_ci_high: float
    # Robustness (from the evidence log).
    has_unresolved_critical_flag: bool = False
    # Not-yet-available higher-gate inputs (later PRs).
    q_value: float | None = None      # BH-FDR q_h (§7.2) — unavailable in PR-3
    holdout_pass: bool | None = None  # §5 holdout gate — unavailable in PR-3


# ---------------------------------------------------------------------------
# Gate + recommendation results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateResult:
    stage: str
    passed: bool
    failures: tuple[str, ...] = ()      # gate conditions that were not met
    unavailable: tuple[str, ...] = ()   # mandatory inputs not yet produced


@dataclass(frozen=True)
class PromotionRecommendation:
    hypothesis_id: str
    recommended_stage: str
    promotion_tier: int                 # ordinal ladder position (NOT an axis sum)
    gates: tuple[GateResult, ...]
    method: str

    def gate_detail(self) -> list[dict[str, Any]]:
        """Serialisable per-gate audit trail for the projection / decision log."""
        return [
            {
                "stage": g.stage,
                "passed": g.passed,
                "failures": list(g.failures),
                "unavailable": list(g.unavailable),
            }
            for g in self.gates
        ]


# ---------------------------------------------------------------------------
# The pure policy
# ---------------------------------------------------------------------------

def _promising_gate(x: PromotionInputs, p: PromotionPolicy) -> GateResult:
    failures: list[str] = []
    if not (x.q_exceed_prob >= p.pi_promising):
        failures.append(f"pi<{p.pi_promising}")
    if not (x.q_precision >= p.prec_promising):
        failures.append(f"prec<{p.prec_promising}")
    if not (x.v_net_sharpe > p.S0):
        failures.append(f"mu_net<=S0({p.S0})")
    if not (x.n_eff >= p.n_eff_promising):
        failures.append(f"n_eff<{p.n_eff_promising}")
    return GateResult(PROMISING, not failures, tuple(failures))


def _validated_gate(x: PromotionInputs, p: PromotionPolicy) -> GateResult:
    failures: list[str] = []
    if not (x.q_exceed_prob >= p.pi_validated):
        failures.append(f"pi<{p.pi_validated}")
    if not (x.q_precision >= p.prec_validated):
        failures.append(f"prec<{p.prec_validated}")
    if not (x.r_sign >= p.rho_sign_validated):
        failures.append(f"rho_sign<{p.rho_sign_validated}")
    if not (x.r_disp >= p.rho_disp_validated):
        failures.append(f"rho_disp<{p.rho_disp_validated}")
    if not (x.replica_count >= p.k_min):
        failures.append(f"m<{p.k_min}")
    if not (x.g_count >= p.g_count_validated):
        failures.append(f"g_count<{p.g_count_validated}")
    if not (x.ci_low >= p.S0):
        failures.append(f"ci_low<S0({p.S0})")
    if x.has_unresolved_critical_flag:
        failures.append("unresolved_critical_robustness_flag")
    return GateResult(VALIDATED, not failures, tuple(failures))


def _production_candidate_gate(x: PromotionInputs, p: PromotionPolicy) -> GateResult:
    failures: list[str] = []
    unavailable: list[str] = []
    if not (x.q_exceed_prob >= p.pi_prodc):
        failures.append(f"pi<{p.pi_prodc}")
    if not (x.r_replicas >= p.rcnt_prodc):
        failures.append(f"R_cnt<{p.rcnt_prodc}")
    if not (x.g_count >= p.g_count_prodc):
        failures.append(f"g_count<{p.g_count_prodc}")
    if not (x.g_coverage >= p.g_cov_prodc):
        failures.append(f"g_cov<{p.g_cov_prodc}")
    if not (x.v_ci_low >= p.S_star):
        failures.append(f"ci_low<S*({p.S_star})")
    # Mandatory gate inputs not yet produced by any merged PR. Absent ⇒ the
    # AND-gate cannot pass; recorded as unavailable, never bypassed.
    if x.q_value is None:
        unavailable.append("bh_fdr_q_value (§7.2 not implemented)")
    elif not (x.q_value <= p.q_max):
        failures.append(f"q>{p.q_max}")
    if x.holdout_pass is None:
        unavailable.append("holdout_pass (§5 not implemented)")
    elif not x.holdout_pass:
        failures.append("holdout_fail")
    passed = not failures and not unavailable
    return GateResult(PRODUCTION_CANDIDATE, passed, tuple(failures), tuple(unavailable))


def recommend(x: PromotionInputs,
              policy: PromotionPolicy = DEFAULT_POLICY) -> PromotionRecommendation:
    """Pure lifecycle recommendation for one hypothesis.

    Walks the promotion ladder contiguously from Candidate: the recommended stage
    is the highest tier for which that tier's AND-of-axes gate — and every gate
    below it — passes. Deterministic and free of RNG / wall-clock.
    """
    gates = (
        _promising_gate(x, policy),
        _validated_gate(x, policy),
        _production_candidate_gate(x, policy),
    )

    reached = CANDIDATE
    for g in gates:                 # ladder order: Promising → Validated → ProdC
        if not g.passed:
            break
        reached = g.stage

    return PromotionRecommendation(
        hypothesis_id=x.hypothesis_id,
        recommended_stage=reached,
        promotion_tier=tier_of(reached),
        gates=gates,
        method=policy.version,
    )
