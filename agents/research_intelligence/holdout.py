"""
holdout.py — the pure ``holdout_v1`` policy (M11 PR-4).

Implements methodology §5 (holdout validation): a **deterministic calendar
partition** of a hypothesis's evidence into in-sample (IS, development) and
out-of-sample (OOS, holdout) windows, and the **two-posteriors-compared** gate
that a hypothesis must pass to be eligible for Production Candidate.

This module is pure: no database, no RNG, no wall-clock. The two posteriors are
produced by the existing ``stat_v1`` engine (`statistics.assess_hypothesis`);
this module only (a) splits evidence by calendar boundary and (b) evaluates the
four §5.2 gate conditions in closed form. It **decides nothing about promotion** —
it emits a holdout evaluation that the Promotion Engine later *consumes*.

§5.2 the holdout passes iff, for IS posterior N(μ_IS, σ_IS²) and OOS posterior
N(μ_OOS, σ_OOS²):

  (a) sign(μ_OOS) = sign(μ_IS)                         — the edge survives OOS
  (b) Pr(θ_OOS > S0) ≥ oos_exceed_min (0.90)           — OOS effect is real
  (c) retention μ_OOS/μ_IS ≥ retention_min (0.50)      — not too much decay
  (d) Pr(θ_IS − θ_OOS > Δ_max) ≤ overlap_prob_max (0.10)  — no overfit blow-off

The realised **haircut** μ_IS/μ_OOS is recorded. Large IS→OOS decay (the overfit
signature) fails (c)/(d) even when the OOS effect is still positive.

Constants (§10 where pinned): holdout fraction π = 0.30, retention r_min = 0.50,
S0 = 0.0; inline §5.2: OOS exceedance ≥ 0.90, overlap prob ≤ 0.10. **Δ_max is not
enumerated in §10** — it is exposed here as a policy knob (default 0.5 = S★, the
economic bar) per the §9 discipline that policy objects hold every constant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from scipy.stats import norm


# ---------------------------------------------------------------------------
# Policy — every §5 constant, versioned ``holdout_v1``
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HoldoutPolicy:
    version: str = "holdout_v1"
    S0: float = 0.0                 # break-even Sharpe (null effect)
    holdout_fraction: float = 0.30  # π — most-recent fraction of the span = OOS (§10)
    retention_min: float = 0.50     # r_min — condition (c) (§10)
    oos_exceed_min: float = 0.90    # condition (b) (§5.2)
    overlap_prob_max: float = 0.10  # condition (d) RHS (§5.2)
    # Δ_max — tolerated IS-over-OOS effect gap in condition (d). Not enumerated in
    # §10; default S★ = 0.5 (a half-Sharpe), configurable.
    delta_max: float = 0.5


DEFAULT_POLICY = HoldoutPolicy()


# ---------------------------------------------------------------------------
# Deterministic calendar partition (§5.1)
# ---------------------------------------------------------------------------

def _parse(d: Any) -> date | None:
    if not d:
        return None
    try:
        return date.fromisoformat(str(d)[:10])
    except (ValueError, TypeError):
        return None


def partition_is_oos(
    rows: list[dict[str, Any]], policy: HoldoutPolicy = DEFAULT_POLICY,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split evidence rows into (IS, OOS) by the §5.1 calendar boundary.

    The boundary is computed **per (market, universe)** from that group's observed
    span: the earliest ⌊(1−π)·span⌋ days are development (IS), the most recent π is
    holdout (OOS). Classification is by an experiment's own window:

      * ``date_end ≤ boundary``   → IS (fully in development)
      * ``date_start > boundary`` → OOS (fully in holdout)
      * otherwise (straddles the boundary, or missing dates) → **IS**

    A straddling experiment used pre-boundary data, so it is never counted as a
    clean OOS test — the OOS set contains only experiments fully inside the holdout
    window. Leakage-safe and a pure, deterministic function of the rows.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r.get("market"), r.get("universe")), []).append(r)

    is_rows: list[dict[str, Any]] = []
    oos_rows: list[dict[str, Any]] = []
    for _, grp in groups.items():
        starts = [d for d in (_parse(r.get("date_start")) for r in grp) if d]
        ends = [d for d in (_parse(r.get("date_end")) for r in grp) if d]
        if not starts or not ends:
            is_rows.extend(grp)          # no usable dates → all development
            continue
        span_start, span_end = min(starts), max(ends)
        total_days = (span_end - span_start).days
        boundary = span_start + timedelta(
            days=math.floor((1.0 - policy.holdout_fraction) * total_days))
        for r in grp:
            ds, de = _parse(r.get("date_start")), _parse(r.get("date_end"))
            if de is not None and de <= boundary:
                is_rows.append(r)
            elif ds is not None and ds > boundary:
                oos_rows.append(r)
            else:
                is_rows.append(r)        # straddle / missing → development
    return is_rows, oos_rows


# ---------------------------------------------------------------------------
# The gate (§5.2) — pure closed-form over two posteriors
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HoldoutResult:
    hypothesis_id: str
    is_mean: float
    is_sd: float
    is_n: int
    oos_mean: float
    oos_sd: float
    oos_n: int
    oos_exceed_prob: float      # Pr(θ_OOS > S0)
    sign_match: bool            # (a)
    retention: float            # μ_OOS / μ_IS
    overlap_prob: float         # Pr(θ_IS − θ_OOS > Δ_max)
    haircut: float | None       # μ_IS / μ_OOS  (None if μ_OOS ≈ 0)
    cond_sign: bool
    cond_exceed: bool
    cond_retention: bool
    cond_overlap: bool
    holdout_pass: bool
    method: str


def _sign(x: float, s0: float) -> int:
    return 1 if x > s0 else -1 if x < s0 else 0


def evaluate_holdout(
    hypothesis_id: str,
    is_mean: float, is_sd: float, is_n: int,
    oos_mean: float, oos_sd: float, oos_n: int,
    policy: HoldoutPolicy = DEFAULT_POLICY,
) -> HoldoutResult:
    """Evaluate the four §5.2 conditions in closed form. Pure and deterministic."""
    s0 = policy.S0

    # (b) OOS exceedance: Pr(θ_OOS > S0).
    oos_exceed = float(norm.cdf((oos_mean - s0) / oos_sd)) if oos_sd > 0 else \
        (1.0 if oos_mean > s0 else 0.0)

    # (a) sign agreement (relative to break-even S0).
    cond_sign = _sign(oos_mean, s0) == _sign(is_mean, s0) and _sign(is_mean, s0) != 0

    # (c) retention μ_OOS/μ_IS ≥ r_min (only meaningful for a positive IS edge).
    is_edge = is_mean - s0
    oos_edge = oos_mean - s0
    retention = (oos_edge / is_edge) if abs(is_edge) > 1e-12 else 0.0
    cond_retention = is_edge > 0 and retention >= policy.retention_min

    # (d) overlap: Pr(θ_IS − θ_OOS > Δ_max) ≤ overlap_prob_max.
    diff_mean = is_mean - oos_mean
    diff_sd = math.sqrt(is_sd ** 2 + oos_sd ** 2)
    if diff_sd > 0:
        overlap_prob = float(norm.sf((policy.delta_max - diff_mean) / diff_sd))
    else:
        overlap_prob = 1.0 if diff_mean > policy.delta_max else 0.0
    cond_overlap = overlap_prob <= policy.overlap_prob_max

    cond_exceed = oos_exceed >= policy.oos_exceed_min

    haircut = (is_edge / oos_edge) if abs(oos_edge) > 1e-12 else None

    holdout_pass = cond_sign and cond_exceed and cond_retention and cond_overlap

    return HoldoutResult(
        hypothesis_id=hypothesis_id,
        is_mean=is_mean, is_sd=is_sd, is_n=is_n,
        oos_mean=oos_mean, oos_sd=oos_sd, oos_n=oos_n,
        oos_exceed_prob=oos_exceed,
        sign_match=cond_sign,
        retention=retention,
        overlap_prob=overlap_prob,
        haircut=haircut,
        cond_sign=cond_sign,
        cond_exceed=cond_exceed,
        cond_retention=cond_retention,
        cond_overlap=cond_overlap,
        holdout_pass=holdout_pass,
        method=policy.version,
    )
