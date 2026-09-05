"""
budget.py — the pure ``budget_v1`` evidence-budget policy (M11 PR-7), §4.

The evidence budget decides **how many future experiments each live hypothesis
may claim**, so research attention flows to where it buys the most learning — with
a hard per-hypothesis ceiling so nothing monopolises the platform.

Pure: no database, no RNG, no wall-clock. It reads posteriors (μ_h, σ_h, mean
se²) and the retirement determination, and produces a deterministic allocation.
This module is a **policy/module, not an agent**; the existing ExplorationPlanner
/ ``research_quota`` consume ``b_h`` through their **existing** ``accept`` seam via
``budget_admission`` — no agent is modified.

§4.1 EVOI (expected value of information):

    EVOI_h = φ((μ_h − g)/√(σ_h² + sē²)) · σ_h · π_h^prom

with φ the standard-normal pdf, ``g`` the nearest effect-space gate threshold
(nearest of {S0, S★} to μ_h), and π_h^prom = Pr(θ_h > S★). EVOI is high for
uncertain-but-promising hypotheses sitting on a threshold, near zero for saturated
(tiny σ) or refuted (π→0) ones.

§4.2 allocation with a per-hypothesis ceiling:

    a_h = clip(EVOI_h / Σ EVOI, a_min, a_max), renormalised ;  b_h = ⌊a_h · B_window⌋

``a_max`` (0.25, §10) is the **hard anti-monopoly ceiling** — no hypothesis may
take more than a quarter of a window, however promising. Retired hypotheses get 0.
``a_min`` (a small exploration floor) is documented as "config" in §10 (not a fixed
value); the default here is 0.01, a ``BudgetPolicy`` knob.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from scipy.stats import norm

_EPS = 1e-12


@dataclass(frozen=True)
class BudgetPolicy:
    version: str = "budget_v1"
    S0: float = 0.0
    S_star: float = 0.5
    a_max: float = 0.25        # hard per-hypothesis ceiling (§10 anti-monopoly)
    a_min: float = 0.01        # exploration floor (§10 "config"; default here)
    default_window: int = 20   # B_window default (scheduling-window experiment slots)


DEFAULT_POLICY = BudgetPolicy()


# ---------------------------------------------------------------------------
# §4.1 — EVOI
# ---------------------------------------------------------------------------

def nearest_gate(mu: float, policy: BudgetPolicy = DEFAULT_POLICY) -> float:
    """The nearest effect-space gate threshold to μ_h (nearest of {S0, S★})."""
    return policy.S0 if abs(mu - policy.S0) <= abs(mu - policy.S_star) else policy.S_star


def evoi(mu: float, sigma: float, mean_se2: float,
         policy: BudgetPolicy = DEFAULT_POLICY) -> float:
    """Expected value of information for one hypothesis (§4.1). Deterministic."""
    if sigma <= 0:
        return 0.0
    pred_sd = math.sqrt(sigma * sigma + max(mean_se2, 0.0))
    if pred_sd <= 0:
        return 0.0
    g = nearest_gate(mu, policy)
    proximity = float(norm.pdf((mu - g) / pred_sd))
    promise = float(norm.cdf((mu - policy.S_star) / sigma))   # π_h^prom = Pr(θ>S★)
    return proximity * sigma * promise


# ---------------------------------------------------------------------------
# §4.2 — allocation with hard ceiling (water-filling) + floor
# ---------------------------------------------------------------------------

def _clip_normalise(shares: dict[str, float], policy: BudgetPolicy) -> dict[str, float]:
    """Clip each share to ``[a_min, a_max]``, then renormalise **down only**.

    The hard ``a_max`` ceiling is absolute, so renormalisation can only ever scale
    shares *down* (never up — that would re-breach the ceiling). When the clipped
    shares already sum to ≤ 1 (e.g. few hypotheses, where the ceiling caps total
    allocation below the window), they are preserved as-is and the remainder is
    left as **exploration headroom** — deliberately *not* inflated up to the
    ceiling, which would spend budget on saturated/low-EVOI incumbents and
    contradict §4 ("less on saturated", "a_min preserves exploration"). Only when
    the clipped shares exceed 1 are they scaled down (staying ≤ a_max, since
    scaling down preserves the ceiling). Deterministic."""
    clipped = {h: min(max(s, policy.a_min), policy.a_max) for h, s in shares.items()}
    total = sum(clipped.values())
    if total > 1.0 + _EPS:
        clipped = {h: s / total for h, s in clipped.items()}
    return clipped


@dataclass(frozen=True)
class Allocation:
    hypothesis_id: str
    evoi: float
    share_raw: float      # EVOI / ΣEVOI before clip
    a_frac: float         # final fraction after ceiling/floor
    b_experiments: int    # ⌊a_frac · window⌋
    capped: bool          # hit the a_max ceiling
    retired: bool


def allocate(
    evoi_by_id: dict[str, float],
    live_ids: set[str],
    window: int,
    policy: BudgetPolicy = DEFAULT_POLICY,
) -> dict[str, Allocation]:
    """Allocate ``b_h`` over the live set (retired ⇒ 0). Deterministic.

    ``evoi_by_id`` may include retired hypotheses; only ``live_ids`` receive a
    share. Shares are EVOI-proportional, water-filled to the hard ``a_max`` ceiling
    and floored at ``a_min``, then converted to integer experiment counts.
    """
    live = sorted(h for h in live_ids)
    n = len(live)
    live_evoi = {h: max(evoi_by_id.get(h, 0.0), 0.0) for h in live}
    total = sum(live_evoi.values())

    if n == 0:
        shares_raw: dict[str, float] = {}
    elif total <= _EPS:
        shares_raw = {h: 1.0 / n for h in live}   # no signal → uniform
    else:
        shares_raw = {h: live_evoi[h] / total for h in live}

    final = _clip_normalise(shares_raw, policy) if live else {}

    out: dict[str, Allocation] = {}
    all_ids = set(evoi_by_id) | live_ids
    for h in sorted(all_ids):
        retired = h not in live_ids
        a = 0.0 if retired else final.get(h, 0.0)
        out[h] = Allocation(
            hypothesis_id=h,
            evoi=evoi_by_id.get(h, 0.0),
            share_raw=0.0 if retired else shares_raw.get(h, 0.0),
            a_frac=a,
            b_experiments=int(math.floor(a * window)),
            capped=(not retired) and a >= policy.a_max - _EPS,
            retired=retired,
        )
    return out


# ---------------------------------------------------------------------------
# §4.3 — consumption adapter for the existing quota `accept` seam
# ---------------------------------------------------------------------------

def budget_admission(
    budget_by_id: dict[str, int],
    key_fn: Callable[[Any], str | None],
) -> Callable[[Any], bool]:
    """Return an ``accept(candidate) -> bool`` gate enforcing the per-hypothesis
    budget ``b_h`` through the ExplorationPlanner's existing ``accept`` seam.

    Generic and decoupled: it imports nothing from ``research_quota`` and takes a
    ``key_fn`` mapping a candidate to its hypothesis_id (``None`` ⇒ the budget does
    not apply, candidate passes). The returned closure holds a transient per-window
    admission tally (not persistent state); given the same candidate sequence it
    admits the same ones — deterministic. A hypothesis with ``b_h = 0`` (including
    retired) admits none.
    """
    remaining: dict[str, int] = dict(budget_by_id)

    def accept(candidate: Any) -> bool:
        hid = key_fn(candidate)
        if hid is None or hid not in remaining:
            return True                 # budget does not govern this candidate
        if remaining[hid] <= 0:
            return False
        remaining[hid] -= 1
        return True

    return accept
