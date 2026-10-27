"""
Monte-Carlo and permutation testing for Project 07.

Provides empirical significance for observed performance by comparing it to a
distribution generated under an explicit **null hypothesis** — that the strategy
has no edge. Two complementary approaches:

- **Monte-Carlo simulation** of null return/equity paths (e.g. sign-randomised or
  parametric-null resampled returns) to build the null distribution of a metric.
- **Permutation testing**, which shuffles the mapping between signal and forward
  return to destroy any genuine predictive relationship while preserving marginal
  distributions.

Determinism: every routine takes an explicit ``seed``.

Scaffold only — all bodies raise ``NotImplementedError``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MonteCarloResult:
    """Result of a Monte-Carlo / permutation significance test.

    Attributes
    ----------
    observed_statistic
        The metric computed on the real data.
    p_value
        Fraction of null draws at least as extreme as ``observed_statistic``.
    null_mean, null_std
        Summary of the simulated null distribution.
    n_iterations
        Number of Monte-Carlo / permutation draws.
    seed
        RNG seed used.
    null_distribution
        The simulated null distribution (length ``n_iterations``).
    """

    observed_statistic: float
    p_value: float
    null_mean: float
    null_std: float
    n_iterations: int
    seed: int
    null_distribution: np.ndarray


def simulate_null_paths(
    returns: pd.Series,
    *,
    n_iterations: int = 10_000,
    model: str = "sign_flip",
    seed: int = 0,
) -> np.ndarray:
    """Generate null return paths under a chosen no-edge model.

    Parameters
    ----------
    returns
        Observed daily return series (used to calibrate the null's marginal
        moments where relevant).
    n_iterations
        Number of null paths to simulate.
    model
        Null-generating model: ``"sign_flip"`` (randomise return signs),
        ``"iid_gaussian"`` (parametric, moment-matched), or ``"block_shuffle"``
        (preserve short-range dependence).
    seed
        RNG seed.

    Returns
    -------
    numpy.ndarray
        Array of shape ``(n_iterations, len(returns))`` of null returns.
    """
    raise NotImplementedError("Monte-Carlo simulation not implemented (scaffold).")


def monte_carlo_pvalue(
    returns: pd.Series,
    metric: Callable[[pd.Series], float],
    *,
    n_iterations: int = 10_000,
    model: str = "sign_flip",
    alternative: str = "greater",
    seed: int = 0,
) -> MonteCarloResult:
    """Empirical p-value for an observed metric under a simulated null.

    Parameters
    ----------
    returns
        Observed daily return series.
    metric
        Callable mapping a return series to a scalar statistic.
    n_iterations
        Number of null simulations.
    model
        Null-generating model (see :func:`simulate_null_paths`).
    alternative
        ``"greater"``, ``"less"``, or ``"two_sided"``.
    seed
        RNG seed.

    Returns
    -------
    MonteCarloResult
        Observed statistic, empirical p-value, and null summary.
    """
    raise NotImplementedError("Monte-Carlo simulation not implemented (scaffold).")


def permutation_test(
    signal: pd.Series,
    forward_return: pd.Series,
    metric: Callable[[pd.Series, pd.Series], float],
    *,
    n_iterations: int = 10_000,
    alternative: str = "greater",
    seed: int = 0,
) -> MonteCarloResult:
    """Permutation test of the signal → forward-return relationship.

    Repeatedly shuffles ``signal`` relative to ``forward_return`` to build the
    null distribution of ``metric`` under no predictive relationship.

    Parameters
    ----------
    signal
        Predictor series (e.g. positions or scores).
    forward_return
        Realised forward returns aligned to ``signal``.
    metric
        Callable mapping ``(signal, forward_return)`` to a scalar.
    n_iterations
        Number of permutations.
    alternative
        ``"greater"``, ``"less"``, or ``"two_sided"``.
    seed
        RNG seed.

    Returns
    -------
    MonteCarloResult
        Observed statistic, empirical p-value, and null summary.
    """
    raise NotImplementedError("permutation testing not implemented (scaffold).")
