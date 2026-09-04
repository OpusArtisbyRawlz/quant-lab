"""
fdr.py — the pure ``fdr_v1`` policy (M11 PR-5), methodology §7.

Deterministic multiple-testing correction over the **whole active population** of
hypotheses. Two controls, exactly as specified:

  * **§7.1 Bayesian FDR (primary).** Each hypothesis has a local false-discovery
    probability ``lfdr_h = Pr(θ_h ≤ S0) = 1 − π_h`` (produced by the stat_v1
    posterior, PR-2). Rank ascending; admit the **largest set D** whose *average*
    lfdr ≤ α. Only hypotheses in D are eligible for Validated+ promotion.
  * **§7.2 Benjamini–Hochberg (frequentist cross-check).** One-sided per-hypothesis
    p-values ``p_h`` — cell p-values combined by weighted Stouffer
    ``Z_h = Σ_c √ω_c·Φ⁻¹(1−p_c) / √(Σ_c ω_c)`` — are BH-adjusted over the whole
    population: ``q_(k) = min_{j≥k} M·p_(j)/j``. The Production-Candidate gate
    additionally requires ``q_h ≤ 0.05``. BY (multiply q by the harmonic sum
    ``Σ 1/j``) is a config switch for high-overlap campaigns.

Pure: no database, no RNG, no wall-clock. The frequentist p-values reuse the
existing stat_v1 per-experiment measurement (deflated Sharpe, se, decay weight
ω_i) — no new estimator and no posterior recomputation.

Constants (§10): α = 0.10; the ProdC BH bar q ≤ 0.05 is fixed by §3.1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

from .statistics import _measure, DEFAULT_POLICY as STAT_DEFAULT_POLICY, StatPolicy, ExperimentEvidence

VARIANT_BH = "bh"
VARIANT_BY = "by"


@dataclass(frozen=True)
class FdrPolicy:
    version: str = "fdr_v1"
    alpha: float = 0.10          # §10 FDR level (Bayesian primary + BH population)
    q_max: float = 0.05          # ProdC BH bar (§3.1)
    variant: str = VARIANT_BH    # "bh" (default) or "by" (high-overlap campaigns)
    S0: float = 0.0              # break-even (null effect)


DEFAULT_POLICY = FdrPolicy()


# ---------------------------------------------------------------------------
# §7.1 — Bayesian FDR admission set D
# ---------------------------------------------------------------------------

def bayesian_fdr_admit(
    lfdr_by_id: dict[str, float], policy: FdrPolicy = DEFAULT_POLICY,
) -> tuple[set[str], float | None]:
    """Admit the largest set D (sorted ascending by lfdr) whose average lfdr ≤ α.

    Returns (admitted_ids, average_lfdr_of_D). Deterministic; ties broken by
    hypothesis_id. Because the list is sorted ascending, the running average is
    non-decreasing, so D is a prefix — the largest k with mean(lfdr[:k]) ≤ α.
    """
    items = sorted(lfdr_by_id.items(), key=lambda kv: (kv[1], kv[0]))
    running = 0.0
    best_k = 0
    best_avg: float | None = None
    for k, (_hid, lfdr) in enumerate(items, start=1):
        running += lfdr
        avg = running / k
        if avg <= policy.alpha:
            best_k = k
            best_avg = avg
    admitted = {items[i][0] for i in range(best_k)}
    return admitted, best_avg


# ---------------------------------------------------------------------------
# §7.2 — one-sided frequentist p_h (weighted Stouffer over cell p-values)
# ---------------------------------------------------------------------------

def hypothesis_pvalue(
    evidence: list[ExperimentEvidence],
    stat_policy: StatPolicy = STAT_DEFAULT_POLICY,
    policy: FdrPolicy = DEFAULT_POLICY,
) -> float | None:
    """One-sided frequentist p-value that θ_h > S0, via weighted Stouffer.

    Per context cell, the decay-weighted inverse-variance combination of the
    deflated per-experiment Sharpes gives a frequentist estimate and se (the
    stat_v1 weights ω_i with **no prior**): ``mean_c = Σω_i·Ŝ_i / Σω_i``,
    ``se_c = 1/√(Σω_i)``, ``z_c = (mean_c − S0)/se_c``, ``ω_c = Σω_i``. Combined:
    ``Z_h = Σ_c √ω_c·z_c / √(Σ_c ω_c)`` and ``p_h = 1 − Φ(Z_h)``.

    Returns ``None`` when there is no usable evidence (no positive-weight cell).
    """
    measured = [_measure(e, stat_policy) for e in evidence]
    by_cell: dict[tuple, list] = {}
    for md in measured:
        by_cell.setdefault(md.cell, []).append(md)

    num = 0.0
    weight_total = 0.0
    for cell in sorted(by_cell):
        mds = by_cell[cell]
        w_c = sum(md.weight for md in mds)
        if w_c <= 0:
            continue
        mean_c = sum(md.weight * md.defl for md in mds) / w_c
        se_c = 1.0 / math.sqrt(w_c)
        z_c = (mean_c - policy.S0) / se_c
        num += math.sqrt(w_c) * z_c
        weight_total += w_c

    if weight_total <= 0:
        return None
    Z_h = num / math.sqrt(weight_total)
    return float(norm.sf(Z_h))       # 1 − Φ(Z_h), one-sided upper tail


# ---------------------------------------------------------------------------
# §7.2 — Benjamini–Hochberg (or BY) q-values over the population
# ---------------------------------------------------------------------------

def benjamini_hochberg(
    pvalue_by_id: dict[str, float], policy: FdrPolicy = DEFAULT_POLICY,
) -> dict[str, float]:
    """BH-adjusted q-values over the whole population. Deterministic.

    ``q_(k) = min_{j≥k} c·M·p_(j)/j`` clamped to ≤ 1, where ``c = 1`` for BH and
    ``c = Σ_{j=1}^M 1/j`` for BY (Benjamini–Yekutieli, high-overlap campaigns).
    Ties broken by hypothesis_id.
    """
    items = sorted(pvalue_by_id.items(), key=lambda kv: (kv[1], kv[0]))
    M = len(items)
    if M == 0:
        return {}
    c = 1.0
    if policy.variant == VARIANT_BY:
        c = sum(1.0 / j for j in range(1, M + 1))

    q_by_id: dict[str, float] = {}
    running_min = math.inf
    for k in range(M, 0, -1):                 # k = M .. 1 (largest p first)
        hid, p_k = items[k - 1]
        running_min = min(running_min, c * M * p_k / k)
        q_by_id[hid] = min(running_min, 1.0)
    return q_by_id
