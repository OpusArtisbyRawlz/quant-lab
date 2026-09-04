"""
statistics — the M11 Bayesian measurement engine (``stat_v1``).

This module is the pure, closed-form implementation of
``docs/M11_STATISTICAL_METHODOLOGY.md`` §§1–2: it turns a set of per-experiment
evidence records for one hypothesis into a **posterior over the latent effect**
plus the **four separated evidence axes** $Q,R,G,V$ — each with an explicit
credible interval. Learning *is* the posterior sharpening as evidence arrives.

Design properties (all required by §9):

  * **No RNG, no wall-clock** — every quantity is closed-form and reproducible.
  * **Event-time decay** — an experiment's weight depends on how many experiments
    elapsed platform-wide since it ran (a count), never on a timestamp, so a
    replay of the log reproduces identical numbers.
  * **Decision-free** — this module *measures*. It never promotes, retires,
    allocates budget, or admits an FDR set. Those are later PRs that read these
    numbers. (The local false-discovery probability ``lfdr = 1 - π`` is reported
    as a cross-check value, not a decision.)
  * **No single confidence scalar** — $Q,R,G,V$ are returned as a vector and are
    never collapsed into one number.

All constants live on the immutable :class:`StatPolicy` (version ``stat_v1``);
changing one bumps the version so historical projections stay reproducible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable, Sequence

from scipy.stats import norm

# --- standard-normal helpers (closed-form, deterministic) ------------------

def _Phi(z: float) -> float:
    """Standard-normal CDF."""
    return float(norm.cdf(z))


def _phi(z: float) -> float:
    """Standard-normal PDF."""
    return float(norm.pdf(z))


def _Phi_inv(p: float) -> float:
    """Standard-normal inverse CDF (quantile)."""
    return float(norm.ppf(p))


# ---------------------------------------------------------------------------
# Policy — every constant from methodology §10 (version stat_v1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatPolicy:
    version: str = "stat_v1"
    S0: float = 0.0           # break-even Sharpe (null effect)
    S_star: float = 0.5       # economic Sharpe bar (V / holdout floor)
    mu0: float = 0.0          # skeptical prior mean
    sigma0: float = 0.5       # skeptical prior sd
    n0: float = 5.0           # precision-adequacy saturation scale
    k_min: int = 3            # minimum independent replicas
    k0: float = 3.0           # replica-count saturation scale
    tau_pi: float = 0.90      # cell posterior bar counting toward G^cnt
    H: float = 200.0          # decay half-life in experiments (math.inf ⇒ no decay)
    lambda_regime: float = 1.0  # off-regime discount (1.0 = off)
    gamma: float = 0.10       # credible level is 1-gamma (default 90%)
    # Fallbacks used only when an evidence record omits T / N (documented
    # convention; richer capture is a recorder enhancement, not a stat change).
    default_N: float = 252.0
    default_T: float = 252.0

    @property
    def phi0(self) -> float:
        return 1.0 / (self.sigma0 ** 2)

    @property
    def z_gamma(self) -> float:
        return _Phi_inv(1.0 - self.gamma / 2.0)


DEFAULT_POLICY = StatPolicy()


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExperimentEvidence:
    """One experiment's realised performance in one context cell (§0 principle 1).

    ``delta`` is the number of experiments elapsed platform-wide since this one
    ran (an event count, not wall-clock) — the decay clock of §6.
    """
    experiment_id: str
    net_sharpe: float
    T: float                       # return periods in the experiment
    N: float = 252.0               # periods per year (BarResult.periods_per_year)
    K: int = 1                     # configurations tried (deflation count)
    delta: float = 0.0             # experiments elapsed platform-wide since i
    market: str = "unknown"
    universe: str = "unknown"
    regime: str = "all"
    bar_type: str = "time"
    date_start: str | None = None
    date_end: str | None = None
    stability: float | None = None  # within-experiment stability sub-score

    @property
    def cell(self) -> tuple[str, str, str, str]:
        return (self.market, self.universe, self.regime, self.bar_type)


# ---------------------------------------------------------------------------
# §1.1 within-experiment likelihood
# ---------------------------------------------------------------------------

def sharpe_se(sharpe: float, T: float, N: float) -> float:
    """Lo (2002) Gaussian standard error of an annualised Sharpe."""
    T = max(float(T), 1.0)
    s_per = sharpe / math.sqrt(N)
    return math.sqrt((1.0 + 0.5 * s_per * s_per) / T) * math.sqrt(N)


def deflated_sharpe(sharpe: float, se: float, K: int) -> float:
    """Deflate a Sharpe for selection over ``K`` configurations (§1.1)."""
    if K is None or K <= 1:
        return sharpe
    return sharpe - se * _Phi_inv(1.0 - 1.0 / K)


# ---------------------------------------------------------------------------
# §6 evidence decay / weight
# ---------------------------------------------------------------------------

def decay_weight(delta: float, H: float) -> float:
    """Exponential forgetting ``d(Δ) = 2^{-Δ/H}``; ``H = inf`` ⇒ 1 (no decay)."""
    if math.isinf(H):
        return 1.0
    return 2.0 ** (-float(delta) / H)


# ---------------------------------------------------------------------------
# Per-experiment measurement (deflated estimate, se, decay-scaled weight)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Measured:
    experiment_id: str
    defl: float          # deflated Sharpe estimate
    se: float
    phi: float           # 1/se^2 (precision)
    weight: float        # omega_i = d(Δ)·λ·phi  (full evidence weight, §6)
    cell: tuple[str, str, str, str]
    date_start: str | None
    date_end: str | None
    stability: float | None


def _measure(e: ExperimentEvidence, policy: StatPolicy) -> _Measured:
    se = sharpe_se(e.net_sharpe, e.T, e.N)
    defl = deflated_sharpe(e.net_sharpe, se, e.K)
    phi = 1.0 / (se * se)
    omega = decay_weight(e.delta, policy.H) * policy.lambda_regime * phi
    return _Measured(e.experiment_id, defl, se, phi, omega, e.cell,
                     e.date_start, e.date_end, e.stability)


# ---------------------------------------------------------------------------
# §1.3 cell posterior (Normal–Normal with exponential forgetting)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CellPosterior:
    cell: tuple[str, str, str, str]
    mu: float
    sigma2: float
    n_eff: float             # Kish effective sample size
    m: int                   # distinct experiments in the cell
    weight_sum: float        # Σ omega_i
    mean_se2: float          # mean se_i^2 (for reproducibility dispersion)
    sign_weight: float       # Σ omega_i · sign(defl_i - S0)

    @property
    def sigma(self) -> float:
        return math.sqrt(self.sigma2)

    def exceed_prob(self, policy: StatPolicy) -> float:
        return _Phi((self.mu - policy.S0) / self.sigma)


def _cell_posterior(cell, measured: Sequence[_Measured],
                    policy: StatPolicy) -> CellPosterior:
    # Reconciled reading of §1.3 + §6: ω_i ≡ d·λ·φ_i is the full evidence weight,
    # and the posterior precision is φ0 + Σ ω_i. At H=inf (ω_i = φ_i) this
    # recovers exact un-decayed conjugate pooling (φ0 + Σ φ_i) — the §9 limit.
    phi_post = policy.phi0
    num = policy.phi0 * policy.mu0
    w_sum = 0.0
    w2_sum = 0.0
    sign_w = 0.0
    se2_sum = 0.0
    for md in measured:
        phi_post += md.weight
        num += md.weight * md.defl
        w_sum += md.weight
        w2_sum += md.weight * md.weight
        sign_w += md.weight * (1.0 if md.defl > policy.S0
                               else -1.0 if md.defl < policy.S0 else 0.0)
        se2_sum += md.se * md.se
    mu = num / phi_post
    sigma2 = 1.0 / phi_post
    n_eff = (w_sum * w_sum / w2_sum) if w2_sum > 0 else 0.0
    m = len({md.experiment_id for md in measured})
    mean_se2 = se2_sum / len(measured) if measured else 0.0
    return CellPosterior(cell, mu, sigma2, n_eff, m, w_sum, mean_se2, sign_w)


# ---------------------------------------------------------------------------
# §1.4 hierarchical pooling: cells → hypothesis (DerSimonian–Laird τ²)
# ---------------------------------------------------------------------------

def dersimonian_laird_tau2(cells: Sequence[CellPosterior]) -> float:
    """Empirical-Bayes between-cell heterogeneity τ² (0 for a single cell)."""
    if len(cells) < 2:
        return 0.0
    w = [1.0 / c.sigma2 for c in cells]
    y = [c.mu for c in cells]
    sw = sum(w)
    y_bar = sum(wi * yi for wi, yi in zip(w, y)) / sw
    Q = sum(wi * (yi - y_bar) ** 2 for wi, yi in zip(w, y))
    df = len(cells) - 1
    c_term = sw - sum(wi * wi for wi in w) / sw
    if c_term <= 0:
        return 0.0
    return max(0.0, (Q - df) / c_term)


@dataclass(frozen=True)
class HypothesisPosterior:
    mu: float
    sigma2: float
    tau2: float
    n_eff: float

    @property
    def sigma(self) -> float:
        return math.sqrt(self.sigma2)


def pool_hypothesis(cells: Sequence[CellPosterior],
                    policy: StatPolicy) -> HypothesisPosterior:
    """Partial-pooling combination of cell posteriors (§1.4)."""
    tau2 = dersimonian_laird_tau2(cells)
    tphi = [1.0 / (c.sigma2 + tau2) for c in cells]
    denom = sum(tphi)
    mu_h = sum(tp * c.mu for tp, c in zip(tphi, cells)) / denom
    sigma2_h = 1.0 / denom
    n_eff = sum(c.n_eff for c in cells)
    return HypothesisPosterior(mu_h, sigma2_h, tau2, n_eff)


def credible_interval(mu: float, sigma: float,
                      policy: StatPolicy) -> tuple[float, float]:
    """Central credible interval at level 1-γ (§1.5)."""
    z = policy.z_gamma
    return (mu - z * sigma, mu + z * sigma)


# ---------------------------------------------------------------------------
# §2 the four evidence axes (never collapsed)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QualityAxis:
    exceed_prob: float       # π_h = Pr(θ_h > S0)
    precision: float         # prec_h = 1 - exp(-n_eff/n0)


@dataclass(frozen=True)
class ReproducibilityAxis:
    sign: float              # ρ^sign
    dispersion: float        # ρ^disp
    replica_score: float     # R^cnt
    stability: float | None  # within-experiment stability (mean), if available
    m: int                   # independent replica count


@dataclass(frozen=True)
class GeneralisationAxis:
    count: int               # G^cnt: cells clearing the bar
    coverage: float          # G^cov: mean fractional coverage over 5 dims


@dataclass(frozen=True)
class ValueAxis:
    net_sharpe: float        # V_h = posterior mean net Sharpe
    ci_low: float
    ci_high: float


def _quality(hp: HypothesisPosterior, policy: StatPolicy) -> QualityAxis:
    pi = _Phi((hp.mu - policy.S0) / hp.sigma)
    prec = 1.0 - math.exp(-hp.n_eff / policy.n0)
    return QualityAxis(pi, prec)


def _reproducibility(cells: Sequence[CellPosterior], measured: Sequence[_Measured],
                     hp: HypothesisPosterior, policy: StatPolicy) -> ReproducibilityAxis:
    w_sum = sum(md.weight for md in measured)
    sign_w = sum(md.weight * (1.0 if md.defl > policy.S0
                              else -1.0 if md.defl < policy.S0 else 0.0)
                 for md in measured)
    rho_sign = abs(sign_w / w_sum) if w_sum > 0 else 0.0
    mean_se2 = (sum(md.se * md.se for md in measured) / len(measured)
                if measured else 0.0)
    rho_disp = 1.0 - hp.tau2 / (hp.tau2 + mean_se2) if (hp.tau2 + mean_se2) > 0 else 1.0
    m = len({md.experiment_id for md in measured})
    r_cnt = (1.0 - math.exp(-m / policy.k0)) if m >= policy.k_min else 0.0
    stabs = [md.stability for md in measured if md.stability is not None]
    stability = sum(stabs) / len(stabs) if stabs else None
    return ReproducibilityAxis(rho_sign, rho_disp, r_cnt, stability, m)


def _generalisation(cells: Sequence[CellPosterior], measured: Sequence[_Measured],
                    policy: StatPolicy) -> GeneralisationAxis:
    passing = [c for c in cells if c.exceed_prob(policy) >= policy.tau_pi]
    g_cnt = len(passing)
    passing_cells = {c.cell for c in passing}
    # Coverage over 5 dimensions: market, universe, regime, bar_type, period.
    # Structural dims come from the cell tuple; period from distinct date windows
    # of experiments that belong to a passing cell.
    dims_all: list[set] = [set(), set(), set(), set(), set()]
    dims_pass: list[set] = [set(), set(), set(), set(), set()]
    for md in measured:
        period = (md.date_start, md.date_end)
        values = (md.cell[0], md.cell[1], md.cell[2], md.cell[3], period)
        is_pass = md.cell in passing_cells
        for d in range(5):
            dims_all[d].add(values[d])
            if is_pass:
                dims_pass[d].add(values[d])
    covs = []
    for d in range(5):
        avail = len(dims_all[d])
        covs.append(len(dims_pass[d]) / avail if avail else 0.0)
    coverage = sum(covs) / 5.0
    return GeneralisationAxis(g_cnt, coverage)


def _value(hp: HypothesisPosterior, policy: StatPolicy) -> ValueAxis:
    lo, hi = credible_interval(hp.mu, hp.sigma, policy)
    return ValueAxis(hp.mu, lo, hi)


# ---------------------------------------------------------------------------
# Top-level: assemble a hypothesis's posterior + axis vector
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HypothesisState:
    """The complete measurement of one hypothesis (posterior + four axes).

    This is a *measurement*, not a decision. ``stage`` is fixed to the initial
    lifecycle value ``'Candidate'`` — PR-2 makes no promotion/retirement
    transition (that is PR-3). ``lfdr`` is the local false-discovery probability
    reported as a cross-check.
    """
    posterior_mean: float
    posterior_sd: float
    ci_low: float
    ci_high: float
    tau2: float
    n_eff: float
    n_supporting: int
    n_contradicting: int
    quality: QualityAxis
    reproducibility: ReproducibilityAxis
    generalisation: GeneralisationAxis
    value: ValueAxis
    lfdr: float
    method: str
    stage: str = "Candidate"


def assess_hypothesis(evidence: Iterable[ExperimentEvidence],
                      policy: StatPolicy = DEFAULT_POLICY) -> HypothesisState:
    """Fold a hypothesis's evidence into a posterior + the four axes.

    Deterministic and order-independent: evidence is grouped by context cell and
    combined by precision-weighted, decay-scaled conjugate updates, so any
    permutation of the same log yields identical output (§9).
    """
    evidence = list(evidence)
    if not evidence:
        raise ValueError("assess_hypothesis requires at least one evidence record")

    measured = [_measure(e, policy) for e in evidence]

    # Group by context cell (sorted for deterministic iteration).
    by_cell: dict[tuple, list[_Measured]] = {}
    for md in measured:
        by_cell.setdefault(md.cell, []).append(md)
    cells = [_cell_posterior(cell, by_cell[cell], policy)
             for cell in sorted(by_cell)]

    hp = pool_hypothesis(cells, policy)
    lo, hi = credible_interval(hp.mu, hp.sigma, policy)

    q = _quality(hp, policy)
    r = _reproducibility(cells, measured, hp, policy)
    g = _generalisation(cells, measured, policy)
    v = _value(hp, policy)

    supporting = len({md.experiment_id for md in measured if md.defl > policy.S0})
    contradicting = len({md.experiment_id for md in measured if md.defl < policy.S0})

    return HypothesisState(
        posterior_mean=hp.mu,
        posterior_sd=hp.sigma,
        ci_low=lo,
        ci_high=hi,
        tau2=hp.tau2,
        n_eff=hp.n_eff,
        n_supporting=supporting,
        n_contradicting=contradicting,
        quality=q,
        reproducibility=r,
        generalisation=g,
        value=v,
        lfdr=1.0 - q.exceed_prob,
        method=policy.version,
    )


__all__ = [
    "StatPolicy", "DEFAULT_POLICY", "ExperimentEvidence",
    "sharpe_se", "deflated_sharpe", "decay_weight",
    "CellPosterior", "HypothesisPosterior", "HypothesisState",
    "QualityAxis", "ReproducibilityAxis", "GeneralisationAxis", "ValueAxis",
    "dersimonian_laird_tau2", "pool_hypothesis", "credible_interval",
    "assess_hypothesis",
]
