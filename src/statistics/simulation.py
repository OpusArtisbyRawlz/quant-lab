"""
Path-robustness and stress simulation for Project 07.

Unlike :mod:`src.statistics.monte_carlo` (which builds *null* distributions for
**significance** testing), this module treats Monte Carlo as a **robustness and
stress-testing** framework. The question is not "is the edge real?" but "how
sensitive is a strategy's outcome to alternative return paths, distributional
assumptions, market environments and regime characteristics?".

It provides, all with an explicit ``rng`` for determinism:

- **Path generators** — Gaussian IID (the textbook baseline), heavy-tailed
  Student-t IID, GARCH(1,1) dynamic volatility (normal or t innovations), and an
  empirical block-bootstrap path builder that *reuses*
  :func:`src.statistics.bootstrap.stationary_bootstrap_indices`.
- **Model fitting & selection** — fit Student-t and GARCH by maximum likelihood
  (scipy only) and pick the *simplest model that materially reproduces* a market's
  observed properties (never the most complex by default).
- **Path metrics** — terminal wealth, CAGR, annualised vol, Sharpe, max drawdown,
  time under water, computed vectorised over a ``(n_paths, horizon)`` matrix, plus
  a reporting summary (percentiles and drawdown/negative-return probabilities).
- **Diagnostics** — per-series moments, quantiles, tail exceedance, return /
  absolute / squared-return autocorrelation (volatility persistence) and drawdown
  characteristics; and a real-vs-synthetic comparison that flags material failures
  to reproduce skew, kurtosis, tails, volatility persistence and drawdowns.
- **Environment stress** — transplant a market's or regime's *risk environment*
  (volatility, tails, persistence) onto a strategy's own mean return. This is an
  explicit stress of the return process, **not** a replay of the strategy on
  another market (its signal inputs do not exist there).

Conventions: returns are simple periodic returns; ``periods_per_year`` defaults to
252; kurtosis is **Pearson** (normal = 3), matching ``pandas.Series.kurt() + 3``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd
from scipy import optimize, stats

from src.statistics.bootstrap import stationary_bootstrap_indices

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #
def _check_returns(returns) -> np.ndarray:
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"returns must be 1-D, got shape {arr.shape}")
    if arr.size == 0:
        raise ValueError("returns must be non-empty")
    if not np.isfinite(arr).all():
        raise ValueError("returns contains non-finite values (NaN/Inf)")
    return arr


def _check_dims(horizon: int, n_paths: int) -> tuple[int, int]:
    for name, v in (("horizon", horizon), ("n_paths", n_paths)):
        if not isinstance(v, (int, np.integer)) or isinstance(v, bool) or v <= 0:
            raise ValueError(f"{name} must be a positive integer, got {v!r}")
    return int(horizon), int(n_paths)


# --------------------------------------------------------------------------- #
# Innovations (standardised: mean 0, variance 1)
# --------------------------------------------------------------------------- #
def gaussian_innovations(n_paths: int, horizon: int, rng: np.random.Generator) -> np.ndarray:
    """Standard-normal innovations, shape ``(n_paths, horizon)``."""
    horizon, n_paths = _check_dims(horizon, n_paths)
    return rng.standard_normal(size=(n_paths, horizon))


def student_t_innovations(
    nu: float, n_paths: int, horizon: int, rng: np.random.Generator
) -> np.ndarray:
    """Standardised Student-t innovations (unit variance), shape ``(n_paths, horizon)``.

    Requires ``nu > 2`` so the variance exists; the raw t is divided by
    ``sqrt(nu/(nu-2))`` so the result has unit variance regardless of ``nu``.
    """
    if not np.isfinite(nu) or nu <= 2:
        raise ValueError(f"nu must be > 2 for finite variance, got {nu!r}")
    horizon, n_paths = _check_dims(horizon, n_paths)
    raw = rng.standard_t(df=nu, size=(n_paths, horizon))
    return raw / np.sqrt(nu / (nu - 2.0))


# --------------------------------------------------------------------------- #
# Parametric path generators
# --------------------------------------------------------------------------- #
def simulate_gaussian(
    mu: float, sigma: float, horizon: int, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    """Gaussian IID paths ``r = mu + sigma * z``, ``z ~ N(0,1)``.

    The canonical textbook Monte Carlo. Assumes constant mean, constant
    volatility, IID innovations and Gaussian (thin) tails.
    """
    if sigma < 0:
        raise ValueError(f"sigma must be non-negative, got {sigma!r}")
    z = gaussian_innovations(n_paths, horizon, rng)
    return mu + sigma * z


def simulate_student_t(
    mu: float, sigma: float, nu: float, horizon: int, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    """Heavy-tailed IID paths: ``mu + sigma * t_std(nu)`` (unit-variance t)."""
    if sigma < 0:
        raise ValueError(f"sigma must be non-negative, got {sigma!r}")
    z = student_t_innovations(nu, n_paths, horizon, rng)
    return mu + sigma * z


def simulate_garch(
    mu: float,
    omega: float,
    alpha: float,
    beta: float,
    horizon: int,
    n_paths: int,
    rng: np.random.Generator,
    *,
    dist: str = "normal",
    nu: Optional[float] = None,
    burn_in: int = 200,
) -> np.ndarray:
    """GARCH(1,1) dynamic-volatility paths.

    ``r_t = mu + eps_t``, ``eps_t = sigma_t * z_t``,
    ``sigma_t^2 = omega + alpha * eps_{t-1}^2 + beta * sigma_{t-1}^2``,
    with ``z_t`` standard normal (``dist="normal"``) or unit-variance Student-t
    (``dist="t"``, ``nu`` required). Volatility clustering and (with t) heavy tails
    are reproduced. A ``burn_in`` is discarded so paths start from the stationary
    variance rather than the seed.
    """
    horizon, n_paths = _check_dims(horizon, n_paths)
    if omega <= 0 or alpha < 0 or beta < 0:
        raise ValueError("require omega > 0, alpha >= 0, beta >= 0")
    if alpha + beta >= 1:
        raise ValueError(f"require alpha + beta < 1 for stationarity, got {alpha + beta}")
    if dist == "t":
        if nu is None:
            raise ValueError("nu required for dist='t'")
        z = student_t_innovations(nu, n_paths, horizon + burn_in, rng)
    elif dist == "normal":
        z = gaussian_innovations(n_paths, horizon + burn_in, rng)
    else:
        raise ValueError(f"dist must be 'normal' or 't', got {dist!r}")

    total = horizon + burn_in
    uncond = omega / (1.0 - alpha - beta)
    eps = np.empty((n_paths, total))
    sig2 = np.empty((n_paths, total))
    sig2[:, 0] = uncond
    eps[:, 0] = np.sqrt(sig2[:, 0]) * z[:, 0]
    for t in range(1, total):
        sig2[:, t] = omega + alpha * eps[:, t - 1] ** 2 + beta * sig2[:, t - 1]
        eps[:, t] = np.sqrt(sig2[:, t]) * z[:, t]
    return mu + eps[:, burn_in:]


def block_bootstrap_paths(
    returns,
    horizon: int,
    n_paths: int,
    expected_block_length: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Empirical dependence-preserving paths via the stationary block bootstrap.

    This is a **bootstrap**, not a parametric Monte Carlo: it resamples contiguous
    blocks of the *observed* returns (reusing
    :func:`stationary_bootstrap_indices`), so it preserves short-run autocorrelation
    and volatility clustering present in the sample — but it can never generate
    returns outside the historical support (no value more extreme than the observed
    min/max is ever produced).
    """
    arr = _check_returns(returns)
    horizon, n_paths = _check_dims(horizon, n_paths)
    out = np.empty((n_paths, horizon))
    n = arr.size
    for p in range(n_paths):
        idx = stationary_bootstrap_indices(n, expected_block_length, rng)
        # stationary_bootstrap_indices returns length-n indices; tile/trim to horizon
        if horizon <= n:
            out[p] = arr[idx[:horizon]]
        else:
            reps = int(np.ceil(horizon / n))
            long_idx = np.concatenate(
                [stationary_bootstrap_indices(n, expected_block_length, rng) for _ in range(reps)]
            )
            out[p] = arr[long_idx[:horizon]]
    return out


# --------------------------------------------------------------------------- #
# Model fitting & selection
# --------------------------------------------------------------------------- #
def fit_student_t(returns) -> dict:
    """Fit a Student-t by MLE (scipy). Returns ``mu``, ``sigma`` (unit-variance
    scale) and ``nu`` (degrees of freedom)."""
    arr = _check_returns(returns)
    nu, loc, scale = stats.t.fit(arr)
    # convert scipy scale to a unit-variance sigma so simulate_student_t matches var
    sigma = scale * np.sqrt(nu / (nu - 2.0)) if nu > 2 else scale
    return {"mu": float(loc), "sigma": float(sigma), "nu": float(nu),
            "loglik": float(np.sum(stats.t.logpdf(arr, nu, loc, scale)))}


def _garch_negloglik(params, x, dist) -> float:
    if dist == "normal":
        mu, omega, alpha, beta = params
        nu = None
    else:
        mu, omega, alpha, beta, nu = params
        if nu <= 2.05:
            return 1e12
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
        return 1e12
    eps = x - mu
    T = eps.size
    sig2 = np.empty(T)
    sig2[0] = np.var(eps)
    for t in range(1, T):
        sig2[t] = omega + alpha * eps[t - 1] ** 2 + beta * sig2[t - 1]
    if not np.all(np.isfinite(sig2)) or np.any(sig2 <= 0):
        return 1e12
    if dist == "normal":
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sig2) + eps ** 2 / sig2)
    else:
        std = eps / np.sqrt(sig2)
        # standardised-t: scale so innovation variance is 1
        s = np.sqrt(nu / (nu - 2.0))
        ll = np.sum(stats.t.logpdf(std * s, nu) + np.log(s) - 0.5 * np.log(sig2))
    return -ll


def _numerical_hessian(fn, x0: np.ndarray, eps_rel: float = 1e-4) -> np.ndarray:
    """Central-difference Hessian of a scalar ``fn`` at ``x0`` (for MLE std errors)."""
    x0 = np.asarray(x0, dtype=float)
    n = x0.size
    h = eps_rel * np.maximum(np.abs(x0), 1e-4)
    H = np.empty((n, n))
    for i in range(n):
        for jj in range(i, n):
            xpp = x0.copy(); xpp[i] += h[i]; xpp[jj] += h[jj]
            xpm = x0.copy(); xpm[i] += h[i]; xpm[jj] -= h[jj]
            xmp = x0.copy(); xmp[i] -= h[i]; xmp[jj] += h[jj]
            xmm = x0.copy(); xmm[i] -= h[i]; xmm[jj] -= h[jj]
            H[i, jj] = H[jj, i] = (fn(xpp) - fn(xpm) - fn(xmp) + fn(xmm)) / (4 * h[i] * h[jj])
    return H


def fit_garch(returns, *, dist: str = "normal", return_se: bool = False) -> dict:
    """Fit GARCH(1,1) by MLE using scipy only (no ``arch`` dependency).

    Returns fitted ``mu, omega, alpha, beta`` (and ``nu`` for ``dist='t'``), the
    log-likelihood, and ``persistence = alpha + beta``. Fitting is done on returns
    scaled to percent for numerical stability, then rescaled to the input units.

    With ``return_se=True`` the routine also reports asymptotic standard errors from
    the inverse numerical Hessian of the negative log-likelihood at the optimum
    (keys ``se_alpha``, ``se_beta``, ``se_nu``, ``se_persistence``). Standard errors
    are ``nan`` when the Hessian is not positive-definite / invertible (reported,
    not hidden). Adding ``return_se`` leaves the default output unchanged.
    """
    arr = _check_returns(returns)
    if dist not in ("normal", "t"):
        raise ValueError(f"dist must be 'normal' or 't', got {dist!r}")
    x = arr * 100.0  # percent units for conditioning
    v = np.var(x)
    if dist == "normal":
        p0 = [np.mean(x), 0.1 * v, 0.05, 0.90]
        bounds = [(None, None), (1e-8, None), (0.0, 0.999), (0.0, 0.999)]
    else:
        p0 = [np.mean(x), 0.1 * v, 0.05, 0.90, 8.0]
        bounds = [(None, None), (1e-8, None), (0.0, 0.999), (0.0, 0.999), (2.1, 200.0)]
    res = optimize.minimize(
        _garch_negloglik, p0, args=(x, dist), method="L-BFGS-B", bounds=bounds
    )
    p = res.x
    mu, omega, alpha, beta = p[0], p[1], p[2], p[3]
    out = {
        "mu": float(mu / 100.0),
        "omega": float(omega / 1e4),   # variance scales by 100^2
        "alpha": float(alpha),
        "beta": float(beta),
        "persistence": float(alpha + beta),
        "loglik": float(-res.fun),
        "converged": bool(res.success),
        "dist": dist,
    }
    if dist == "t":
        out["nu"] = float(p[4])

    if return_se:
        se = {"se_alpha": float("nan"), "se_beta": float("nan"),
              "se_persistence": float("nan"), "se_nu": float("nan")}
        try:
            H = _numerical_hessian(lambda q: _garch_negloglik(q, x, dist), p)
            cov = np.linalg.inv(H)                     # inverse observed information
            diag = np.diag(cov)
            if np.all(diag > 0):
                # alpha, beta are scale-free (indices 2, 3); nu (index 4) too
                se["se_alpha"] = float(np.sqrt(diag[2]))
                se["se_beta"] = float(np.sqrt(diag[3]))
                var_persist = diag[2] + diag[3] + 2 * cov[2, 3]
                se["se_persistence"] = float(np.sqrt(var_persist)) if var_persist > 0 else float("nan")
                if dist == "t":
                    se["se_nu"] = float(np.sqrt(diag[4]))
        except (np.linalg.LinAlgError, ValueError):
            pass
        out.update(se)
    return out


def _acf(x: np.ndarray, lags) -> dict:
    x = x - x.mean()
    denom = np.sum(x * x)
    out = {}
    for k in lags:
        out[k] = float(np.sum(x[k:] * x[:-k]) / denom) if denom > 0 and k < x.size else float("nan")
    return out


def select_return_model(
    returns,
    *,
    kurt_threshold: float = 4.0,
    sq_acf_threshold: float = 0.05,
    seed: int = 0,
) -> dict:
    """Pick the **simplest** generator that materially reproduces the data.

    Hierarchy (only escalate when the data demand it):

    1. **Gaussian IID** — default.
    2. **Student-t IID** — if Pearson kurtosis exceeds ``kurt_threshold`` (heavy
       tails) but there is little volatility clustering.
    3. **GARCH(1,1)-normal** — if squared-return autocorrelation (lag 1) exceeds
       ``sq_acf_threshold`` (volatility clustering) but tails are near-Gaussian.
    4. **GARCH(1,1)-t** — if both heavy tails *and* volatility clustering.

    Returns the selected model name, its fitted params, the deciding diagnostics
    and a human-readable rationale.
    """
    arr = _check_returns(returns)
    kurt = float(stats.kurtosis(arr, fisher=False))          # Pearson (normal = 3)
    sq_acf1 = _acf(arr ** 2, [1])[1]
    heavy = kurt > kurt_threshold
    clustered = np.isfinite(sq_acf1) and sq_acf1 > sq_acf_threshold

    diagnostics = {"pearson_kurtosis": kurt, "sq_return_acf_lag1": float(sq_acf1),
                   "heavy_tails": bool(heavy), "vol_clustering": bool(clustered)}

    if heavy and clustered:
        model, params = "garch_t", fit_garch(arr, dist="t")
        rationale = (f"heavy tails (kurtosis {kurt:.1f} > {kurt_threshold}) AND volatility "
                     f"clustering (sq-return ACF₁ {sq_acf1:.3f} > {sq_acf_threshold}) "
                     f"→ GARCH(1,1) with Student-t innovations.")
    elif clustered:
        model, params = "garch_normal", fit_garch(arr, dist="normal")
        rationale = (f"volatility clustering (sq-return ACF₁ {sq_acf1:.3f} > {sq_acf_threshold}) "
                     f"with near-Gaussian tails → GARCH(1,1)-normal.")
    elif heavy:
        model, params = "student_t", fit_student_t(arr)
        rationale = (f"heavy tails (kurtosis {kurt:.1f} > {kurt_threshold}) without strong "
                     f"clustering → Student-t IID.")
    else:
        model = "gaussian"
        params = {"mu": float(arr.mean()), "sigma": float(arr.std(ddof=1))}
        rationale = (f"near-Gaussian (kurtosis {kurt:.1f} ≤ {kurt_threshold}, sq-return ACF₁ "
                     f"{sq_acf1:.3f} ≤ {sq_acf_threshold}) → simplest Gaussian IID adequate.")
    return {"model": model, "params": params, "diagnostics": diagnostics, "rationale": rationale}


def simulate_from_model(
    selection: dict, horizon: int, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    """Generate paths from a :func:`select_return_model` (or compatible) result."""
    model, p = selection["model"], selection["params"]
    if model == "gaussian":
        return simulate_gaussian(p["mu"], p["sigma"], horizon, n_paths, rng)
    if model == "student_t":
        return simulate_student_t(p["mu"], p["sigma"], p["nu"], horizon, n_paths, rng)
    if model == "garch_normal":
        return simulate_garch(p["mu"], p["omega"], p["alpha"], p["beta"],
                              horizon, n_paths, rng, dist="normal")
    if model == "garch_t":
        return simulate_garch(p["mu"], p["omega"], p["alpha"], p["beta"],
                              horizon, n_paths, rng, dist="t", nu=p["nu"])
    raise ValueError(f"unknown model {model!r}")


def regime_switching_paths(
    horizon: int,
    n_paths: int,
    rng: np.random.Generator,
    *,
    p_enter_high: float,
    p_stay_high: float,
    sigma_calm: float,
    sigma_high: float,
    nu_calm: float,
    nu_high: float,
    high_drift: float = 0.0,
) -> tuple[np.ndarray, float]:
    """Two-state (calm / high-vol) Markov regime-switching return environment.

    A first-order Markov chain switches between a *calm* state (daily vol
    ``sigma_calm``, Student-t innovations with ``nu_calm``) and a *high-vol* state
    (``sigma_high``, ``nu_high``, plus an optional negative ``high_drift`` for a
    heavier-loss stress). Transition probabilities are ``p_enter_high`` (calm→high)
    and ``p_stay_high`` (high→high); the implied stationary high-vol fraction is
    ``p_enter / (1 - p_stay + p_enter)``.

    This is designed for **stress scenarios** (raise the high-vol frequency,
    persistence or tail heaviness above the historically observed values) — it is a
    what-if environment, not a forecast. The chain is vectorised across paths (one
    Python loop over the horizon). Returns ``(paths, realised_high_fraction)``.
    """
    horizon, n_paths = _check_dims(horizon, n_paths)
    for name, v in (("p_enter_high", p_enter_high), ("p_stay_high", p_stay_high)):
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"{name} must be in [0, 1], got {v!r}")
    u = rng.random((n_paths, horizon))
    states = np.empty((n_paths, horizon), dtype=np.int8)
    cur = np.zeros(n_paths, dtype=np.int8)
    for t in range(horizon):
        thresh = np.where(cur == 1, p_stay_high, p_enter_high)
        cur = (u[:, t] < thresh).astype(np.int8)
        states[:, t] = cur
    zc = student_t_innovations(nu_calm, n_paths, horizon, rng)
    zh = student_t_innovations(nu_high, n_paths, horizon, rng)
    paths = np.where(states == 1, sigma_high * zh + high_drift, sigma_calm * zc)
    return paths, float(states.mean())


# --------------------------------------------------------------------------- #
# Environment / regime stress (return-process transplant)
# --------------------------------------------------------------------------- #
def environment_stress_paths(
    strategy_returns,
    env_paths: np.ndarray,
    *,
    preserve_mean: bool = True,
) -> np.ndarray:
    """Transplant an environment's *risk* (vol, tails, persistence) onto a strategy.

    Given synthetic ``env_paths`` (from a market- or regime-calibrated generator),
    the standardised innovations of the environment are combined with the
    **strategy's own daily mean** (its edge) and the environment's daily volatility:

        ``r = mu_strategy + (env_path - mean(env_path)) if preserve_mean``.

    This is an explicit **stress of the strategy's return process** under another
    environment's risk characteristics — it is *not* a replay of the strategy on
    that market (the strategy's signal inputs do not exist there). Use it only with
    that labelling.
    """
    s = _check_returns(strategy_returns)
    env = np.asarray(env_paths, dtype=float)
    if env.ndim != 2:
        raise ValueError(f"env_paths must be 2-D (n_paths, horizon), got {env.shape}")
    if preserve_mean:
        return s.mean() + (env - env.mean(axis=1, keepdims=True))
    return env


# --------------------------------------------------------------------------- #
# Path metrics (vectorised over (n_paths, horizon))
# --------------------------------------------------------------------------- #
def _as_matrix(paths) -> np.ndarray:
    m = np.asarray(paths, dtype=float)
    if m.ndim == 1:
        m = m[None, :]
    if m.ndim != 2:
        raise ValueError(f"paths must be 1-D or 2-D, got shape {m.shape}")
    return m


def terminal_wealth(paths) -> np.ndarray:
    """Terminal wealth of each path (start = 1.0)."""
    return np.prod(1.0 + _as_matrix(paths), axis=1)


def path_cagr(paths, periods_per_year: int = TRADING_DAYS) -> np.ndarray:
    m = _as_matrix(paths)
    tw = np.prod(1.0 + m, axis=1)
    return np.sign(tw) * np.abs(tw) ** (periods_per_year / m.shape[1]) - 1.0


def path_ann_vol(paths, periods_per_year: int = TRADING_DAYS) -> np.ndarray:
    return _as_matrix(paths).std(axis=1, ddof=1) * np.sqrt(periods_per_year)


def path_sharpe(paths, periods_per_year: int = TRADING_DAYS) -> np.ndarray:
    m = _as_matrix(paths)
    mean = m.mean(axis=1)
    sd = m.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, mean / sd * np.sqrt(periods_per_year), np.nan)


def path_max_drawdown(paths) -> np.ndarray:
    """Max drawdown of each path (negative), vectorised."""
    m = _as_matrix(paths)
    equity = np.cumprod(1.0 + m, axis=1)
    running_max = np.maximum.accumulate(equity, axis=1)
    return (equity / running_max - 1.0).min(axis=1)


def path_time_under_water(paths) -> np.ndarray:
    """Fraction of each path spent below the prior equity peak."""
    m = _as_matrix(paths)
    equity = np.cumprod(1.0 + m, axis=1)
    running_max = np.maximum.accumulate(equity, axis=1)
    return (equity < running_max - 1e-12).mean(axis=1)


def path_max_underwater_days(paths) -> np.ndarray:
    """Longest underwater run (peak→recovery) in periods, per path (recovery proxy).

    Counts the longest consecutive stretch each path spends strictly below its prior
    equity peak. A path that ends underwater reports the length of that final,
    unrecovered stretch.
    """
    m = _as_matrix(paths)
    equity = np.cumprod(1.0 + m, axis=1)
    underwater = (equity < np.maximum.accumulate(equity, axis=1) - 1e-12).astype(int)
    # longest consecutive run of 1s per row: loop over time, vectorised over paths
    run = np.zeros(m.shape[0], dtype=int)
    best = np.zeros(m.shape[0], dtype=int)
    for t in range(m.shape[1]):
        run = (run + underwater[:, t]) * underwater[:, t]
        best = np.maximum(best, run)
    return best.astype(float)


# --------------------------------------------------------------------------- #
# Path-dependent exposure overlays (vectorised, for dynamic strategy replay)
# --------------------------------------------------------------------------- #
# These reproduce ``src.risk.drawdown`` (compute_drawdown, drawdown_exposure_smooth,
# apply_exposure_to_return) but vectorised over a (n_paths, horizon) matrix, so a
# path-dependent risk policy can be *recomputed from simulated states* rather than
# reusing historical exposure decisions. Consistency with the pandas originals is
# guarded by tests.
def drawdown_paths(returns_paths) -> np.ndarray:
    """Running drawdown series (equity/cummax − 1 ≤ 0) for each path."""
    m = _as_matrix(returns_paths)
    equity = np.cumprod(1.0 + m, axis=1)
    return equity / np.maximum.accumulate(equity, axis=1) - 1.0


def smooth_dd_exposure(drawdown: np.ndarray, floor: float, k: float) -> np.ndarray:
    """Smooth drawdown→exposure map ``floor + (1-floor)·exp(-k·|dd|)``.

    Matches :func:`src.risk.drawdown.drawdown_exposure_smooth`. Returns the
    *as-computed* (un-lagged) exposure; lag it with :func:`apply_lagged_exposure`.
    """
    if not 0.0 <= floor <= 1.0:
        raise ValueError(f"floor must be in [0, 1], got {floor!r}")
    if k < 0:
        raise ValueError(f"k must be >= 0, got {k!r}")
    return floor + (1.0 - floor) * np.exp(-k * np.abs(drawdown))


def rolling_vol_multiplier(
    returns_paths, *, window: int = 252, periods_per_year: int = TRADING_DAYS,
    power: float = 0.5, clip=(0.7, 1.3),
) -> np.ndarray:
    """Volatility multiplier ``(rv/mean(rv))**power`` clipped, per path.

    ``rv`` is the rolling annualised stdev over ``window``; the normaliser is each
    path's own mean realised vol. Reproduces the shipped ``vol_multiplier``
    functional form. Leading (pre-``window``) values are set to 1.0. The
    self-normalisation uses the whole path (as the shipped overlay did); this is an
    in-sample normaliser, flagged where it matters.
    """
    m = _as_matrix(returns_paths)
    P, T = m.shape
    out = np.ones((P, T))
    if T < window + 1:
        return out
    for i in range(P):
        s = pd.Series(m[i])
        rv = (s.rolling(window).std() * np.sqrt(periods_per_year))
        mult = (rv / rv.mean()) ** power
        mult = np.array(mult.clip(clip[0], clip[1]).to_numpy(), dtype=float)
        mult[np.isnan(mult)] = 1.0
        out[i] = mult
    return out


def apply_lagged_exposure(returns_paths, exposure: np.ndarray) -> np.ndarray:
    """Apply exposure to returns with a 1-period lag (no look-ahead).

    ``r_t * exposure_{t-1}`` with ``exposure_{-1}=1``. Matches the shift-by-1
    convention of :func:`src.risk.drawdown.apply_exposure_to_return`.
    """
    m = _as_matrix(returns_paths)
    e = np.asarray(exposure, dtype=float)
    if e.shape != m.shape:
        raise ValueError(f"exposure shape {e.shape} must match returns {m.shape}")
    lagged = np.empty_like(e)
    lagged[:, 0] = 1.0
    lagged[:, 1:] = e[:, :-1]
    return m * lagged


def summarize_path_metrics(
    paths,
    *,
    periods_per_year: int = TRADING_DAYS,
    mdd_thresholds=(-0.20, -0.30, -0.40),
    wealth_percentiles=(5, 25, 50, 75, 95),
) -> dict:
    """Reporting summary of a path-metric distribution (one strategy/environment)."""
    m = _as_matrix(paths)
    cagr = path_cagr(m, periods_per_year)
    mdd = path_max_drawdown(m)
    tw = terminal_wealth(m)
    out = {
        "n_paths": int(m.shape[0]),
        "horizon": int(m.shape[1]),
        "median_cagr": float(np.median(cagr)),
        "p5_cagr": float(np.percentile(cagr, 5)),
        "median_ann_vol": float(np.median(path_ann_vol(m, periods_per_year))),
        "median_sharpe": float(np.nanmedian(path_sharpe(m, periods_per_year))),
        "median_mdd": float(np.median(mdd)),
        "p5_mdd": float(np.percentile(mdd, 5)),        # worst-tail (most negative) MDD
        "worst_mdd": float(mdd.min()),
        "median_time_under_water": float(np.median(path_time_under_water(m))),
        "prob_cagr_negative": float(np.mean(cagr < 0)),
    }
    for thr in mdd_thresholds:
        out[f"prob_mdd_below_{int(abs(thr)*100)}pct"] = float(np.mean(mdd < thr))
    for q in wealth_percentiles:
        out[f"terminal_wealth_p{q}"] = float(np.percentile(tw, q))
    return out


# --------------------------------------------------------------------------- #
# Diagnostics & synthetic-vs-real validation
# --------------------------------------------------------------------------- #
def return_diagnostics(returns, *, periods_per_year: int = TRADING_DAYS, acf_lags=(1, 2, 5, 10)) -> dict:
    """Empirical statistical properties of a single return series."""
    arr = _check_returns(returns)
    equity = np.cumprod(1.0 + arr)
    running_max = np.maximum.accumulate(equity)
    dd = equity / running_max - 1.0
    q = np.percentile(arr, [1, 5, 95, 99])
    sd = arr.std(ddof=1)
    out = {
        "n_obs": int(arr.size),
        "mean": float(arr.mean()),
        "std": float(sd),
        "ann_vol": float(sd * np.sqrt(periods_per_year)),
        "skewness": float(stats.skew(arr)),
        "kurtosis": float(stats.kurtosis(arr, fisher=False)),   # Pearson (normal = 3)
        "q01": float(q[0]), "q05": float(q[1]), "q95": float(q[2]), "q99": float(q[3]),
        "min": float(arr.min()), "max": float(arr.max()),
        "tail_exceed_below_q01_freq": float(np.mean(arr < q[0])),
        "tail_exceed_above_q99_freq": float(np.mean(arr > q[3])),
        "max_drawdown": float(dd.min()),
        "time_under_water": float((dd < -1e-12).mean()),
    }
    for k, v in _acf(arr, acf_lags).items():
        out[f"acf_ret_lag{k}"] = v
    for k, v in _acf(np.abs(arr), acf_lags).items():
        out[f"acf_abs_lag{k}"] = v
    for k, v in _acf(arr ** 2, acf_lags).items():
        out[f"acf_sq_lag{k}"] = v
    return out


def synthetic_vs_real(
    real_returns,
    sim_paths: np.ndarray,
    *,
    periods_per_year: int = TRADING_DAYS,
    tol_rel: float = 0.30,
) -> dict:
    """Compare synthetic paths to the real series and flag material fit failures.

    A generator is judged not on mean/vol alone but on whether it reproduces
    **skew, kurtosis, tails and volatility persistence** (squared-return ACF₁) and
    drawdown severity. For each property we report real vs synthetic-median and a
    ``pass`` flag (relative error within ``tol_rel``, or sign match for skew). The
    per-path statistics are pooled across ``sim_paths``.
    """
    real = _check_returns(real_returns)
    m = _as_matrix(sim_paths)

    def col(fn):
        return np.array([fn(m[i]) for i in range(m.shape[0])])

    real_props = {
        "std": real.std(ddof=1),
        "skewness": stats.skew(real),
        "kurtosis": stats.kurtosis(real, fisher=False),
        "q01": np.percentile(real, 1),
        "q99": np.percentile(real, 99),
        "sq_acf_lag1": _acf(real ** 2, [1])[1],
        "max_drawdown": float(path_max_drawdown(real)[0]),
    }
    sim_props = {
        "std": np.median(m.std(axis=1, ddof=1)),
        "skewness": np.median(col(lambda r: stats.skew(r))),
        "kurtosis": np.median(col(lambda r: stats.kurtosis(r, fisher=False))),
        "q01": np.median(np.percentile(m, 1, axis=1)),
        "q99": np.median(np.percentile(m, 99, axis=1)),
        "sq_acf_lag1": np.median(col(lambda r: _acf(r ** 2, [1])[1])),
        "max_drawdown": np.median(path_max_drawdown(m)),
    }
    rows = {}
    for key in real_props:
        r_val, s_val = float(real_props[key]), float(sim_props[key])
        if key == "skewness":
            ok = (np.sign(r_val) == np.sign(s_val)) or abs(r_val - s_val) < 0.2
        else:
            denom = abs(r_val) if abs(r_val) > 1e-12 else 1.0
            ok = abs(s_val - r_val) / denom <= tol_rel
        rows[key] = {"real": r_val, "synthetic_median": s_val, "pass": bool(ok)}
    rows["_material_failures"] = [k for k, v in rows.items()
                                  if isinstance(v, dict) and not v["pass"]]
    return rows
