"""
Data-snooping tests for Project 07: White's Reality Check and Hansen's SPA.

When the "best" strategy is chosen from a family evaluated on the same data, its
performance is upward-biased by the selection itself. These tests ask whether the
best strategy in the family beats a benchmark *after accounting for the full set
of strategies searched*:

- **White's Reality Check (2000)** — bootstrap test of the null that the best
  model has no predictive superiority over the benchmark.
- **Hansen's Superior Predictive Ability (SPA, 2005)** — a more powerful refinement
  that is robust to the inclusion of poor/irrelevant strategies in the family.

Both require the per-strategy performance series (e.g. excess returns vs the
benchmark) for every candidate in the family, and use a stationary bootstrap over
the time dimension. Determinism via an explicit ``seed``.

Scaffold only — all bodies raise ``NotImplementedError``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.statistics.bootstrap import stationary_bootstrap_indices


@dataclass(frozen=True)
class RealityCheckResult:
    """Result of a data-snooping test over a strategy family.

    Attributes
    ----------
    test
        ``"white_reality_check"`` or ``"hansen_spa"``.
    best_strategy
        Identifier (column) of the best-performing strategy in the family.
    best_statistic
        The performance statistic of the best strategy vs the benchmark
        (here ``sqrt(T) * mean(d_k)`` for the winning strategy).
    p_value
        Bootstrap p-value for the null that no strategy in the family beats the
        benchmark once the search is accounted for (add-one estimator).
    n_strategies
        Number of strategies in the family.
    n_resamples
        Number of bootstrap resamples.
    seed
        RNG seed used.
    null_q95, null_q99
        95th / 99th percentiles of the bootstrap distribution of the *maximum*
        statistic under the recentred null.
    """

    test: str
    best_strategy: str
    best_statistic: float
    p_value: float
    n_strategies: int
    n_resamples: int
    seed: int
    null_q95: float = float("nan")
    null_q99: float = float("nan")


def reality_check(
    performance: pd.DataFrame,
    *,
    n_resamples: int = 10_000,
    expected_block_length: float = 20.0,
    seed: int = 0,
) -> RealityCheckResult:
    """White's Reality Check over a family of strategies.

    Parameters
    ----------
    performance
        Wide frame of per-strategy performance vs the benchmark, indexed by date,
        one column per candidate strategy (e.g. excess returns or loss
        differentials).
    n_resamples
        Number of stationary-bootstrap resamples.
    expected_block_length
        Mean block length for the stationary bootstrap.
    seed
        RNG seed.

    Returns
    -------
    RealityCheckResult
        The best strategy and the family-adjusted p-value.

    Notes
    -----
    Implements White's (2000) Reality Check on the **mean** performance
    differential. With ``d_{k,t}`` the (T x K) matrix of per-strategy differentials
    vs the benchmark and ``dbar_k`` its column means, the statistic is

    ``V = max_k sqrt(T) * dbar_k``.

    The null ``H0: max_k E[d_k] <= 0`` is imposed by **recentring** each column to
    zero mean (``d~_{k,t} = d_{k,t} - dbar_k``). Each bootstrap replication draws
    **one** set of stationary-bootstrap indices and applies it to **all** columns
    simultaneously (via :func:`stationary_bootstrap_indices`), preserving
    cross-strategy dependence — strategies are never resampled independently. The
    p-value uses the add-one convention ``p = (#{V* >= V} + 1) / (B + 1)``.

    This function is strategy-name agnostic: it operates on the columns of
    ``performance`` and returns the winning column label.

    Raises
    ------
    ValueError
        If ``performance`` is empty, has fewer than 2 rows, is non-numeric, or
        contains non-finite values; or if ``n_resamples`` is not a positive
        integer. (Invalid ``expected_block_length`` is raised by the delegated
        index call.)
    """
    df = pd.DataFrame(performance)
    if df.shape[1] == 0 or df.shape[0] == 0:
        raise ValueError("performance must be a non-empty 2-D frame (dates x strategies)")
    if df.shape[0] < 2:
        raise ValueError(f"performance needs at least 2 observations, got {df.shape[0]}")
    values = df.to_numpy()
    if not np.issubdtype(values.dtype, np.number):
        raise ValueError(f"performance must be numeric, got dtype {values.dtype!r}")
    if not np.isfinite(values).all():
        raise ValueError("performance contains non-finite values (NaN/Inf)")
    if not isinstance(n_resamples, (int, np.integer)) or isinstance(n_resamples, bool) \
            or n_resamples <= 0:
        raise ValueError(f"n_resamples must be a positive integer, got {n_resamples!r}")

    D = values.astype(float)                       # (T, K)
    T, K = D.shape
    columns = list(df.columns)

    dbar = D.mean(axis=0)                           # (K,)
    observed = np.sqrt(T) * dbar                    # per-strategy statistic
    best_idx = int(np.argmax(observed))
    V = float(observed[best_idx])

    Dc = D - dbar                                   # recentred under the null (col mean 0)
    rng = np.random.default_rng(seed)
    n_resamples = int(n_resamples)
    null_max = np.empty(n_resamples, dtype=float)
    for b in range(n_resamples):
        idx = stationary_bootstrap_indices(T, expected_block_length, rng)  # shared across strategies
        boot_mean = Dc[idx].mean(axis=0)           # (K,)
        null_max[b] = np.max(np.sqrt(T) * boot_mean)

    p_value = (int(np.sum(null_max >= V)) + 1) / (n_resamples + 1)   # add-one
    return RealityCheckResult(
        test="white_reality_check",
        best_strategy=columns[best_idx],
        best_statistic=V,
        p_value=float(p_value),
        n_strategies=K,
        n_resamples=n_resamples,
        seed=int(seed),
        null_q95=float(np.percentile(null_max, 95)),
        null_q99=float(np.percentile(null_max, 99)),
    )


def superior_predictive_ability(
    performance: pd.DataFrame,
    *,
    n_resamples: int = 10_000,
    expected_block_length: float = 20.0,
    seed: int = 0,
) -> RealityCheckResult:
    """Hansen's Superior Predictive Ability (SPA) test over a strategy family.

    More powerful than the Reality Check and robust to the presence of poor
    strategies in the family.

    Parameters
    ----------
    performance
        Wide frame of per-strategy performance vs the benchmark (see
        :func:`reality_check`).
    n_resamples
        Number of stationary-bootstrap resamples.
    expected_block_length
        Mean block length for the stationary bootstrap.
    seed
        RNG seed.

    Returns
    -------
    RealityCheckResult
        The best strategy and the SPA p-value.
    """
    raise NotImplementedError("Hansen SPA not implemented (scaffold).")
