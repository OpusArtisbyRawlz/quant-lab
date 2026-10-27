"""Probability of Backtest Overfitting (PBO) via Combinatorially Symmetric Cross-Validation.

Implements the CSCV / PBO estimator of Bailey, Borwein, López de Prado & Zhu (2014),
*The Probability of Backtest Overfitting*:

Given a matrix ``M`` of shape ``(T, N)`` holding the per-period performance contribution of ``N``
candidate strategies over ``T`` observations:

1. Partition the ``T`` rows into ``S`` disjoint contiguous submatrices (``S`` even).
2. For every combination of ``S/2`` submatrices forming the in-sample (IS) set, the complementary
   ``S/2`` form the out-of-sample (OOS) set (this is the "combinatorially symmetric" design — IS
   and OOS have equal size and every split has a mirror).
3. Pick the IS-optimal strategy ``n*`` under a predefined objective (default: Sharpe of the pooled
   IS rows).
4. Evaluate every strategy OOS; find the OOS rank of ``n*`` -> relative rank ``w in (0,1)``.
5. Logit ``lambda = ln(w / (1 - w))``. PBO = ``P(lambda <= 0)`` = fraction of splits where the
   IS-best strategy lands at or below the OOS median.

PBO answers a different question from DSR / White's RC / PSR: it estimates the probability that the
*selection procedure* picks a strategy that will underperform the median OOS — i.e. selection
overfitting — rather than whether a single strategy beats a benchmark after one round of selection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

__all__ = ["sharpe_objective", "mean_objective", "pbo_cscv", "PBOResult"]

TRADING_DAYS = 252


def sharpe_objective(block: np.ndarray, periods_per_year: int = TRADING_DAYS) -> np.ndarray:
    """Annualised Sharpe per column of a (rows, N) block (ddof=1)."""
    mu = block.mean(axis=0)
    sd = block.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sr = np.where(sd > 0, mu / sd * np.sqrt(periods_per_year), -np.inf)
    return sr


def mean_objective(block: np.ndarray, periods_per_year: int = TRADING_DAYS) -> np.ndarray:
    return block.mean(axis=0)


@dataclass
class PBOResult:
    pbo: float
    n_splits: int
    n_strategies: int
    S: int
    logits: np.ndarray = field(repr=False)
    oos_relative_ranks: np.ndarray = field(repr=False)
    is_selected: np.ndarray = field(repr=False)          # chosen strategy index per split
    oos_performance_of_selected: np.ndarray = field(repr=False)
    median_oos_of_selected: float = 0.0
    prob_oos_loss: float = 0.0                            # fraction of splits selected strat OOS < 0 metric


def pbo_cscv(M: np.ndarray, S: int = 16, *, objective=sharpe_objective,
             periods_per_year: int = TRADING_DAYS) -> PBOResult:
    """Estimate PBO by CSCV.

    Parameters
    ----------
    M : (T, N) array of per-period performance contributions (e.g. daily returns) for N candidates.
    S : even number of contiguous row-partitions. Number of symmetric splits is C(S, S/2).
    objective : callable(block)->(N,) array scoring each strategy on a set of pooled rows.
    """
    M = np.asarray(M, dtype=float)
    if M.ndim != 2:
        raise ValueError("M must be 2-D (T, N)")
    T, N = M.shape
    if N < 2:
        raise ValueError("need >= 2 candidate strategies")
    if S < 2 or S % 2 != 0:
        raise ValueError("S must be an even integer >= 2")
    if T < S:
        raise ValueError("T must be >= S")

    bounds = np.linspace(0, T, S + 1).astype(int)
    parts = [np.arange(bounds[s], bounds[s + 1]) for s in range(S)]
    half = S // 2

    logits, ranks, selected, oos_sel = [], [], [], []
    for is_combo in combinations(range(S), half):
        oos_combo = tuple(s for s in range(S) if s not in is_combo)
        is_rows = np.concatenate([parts[s] for s in is_combo])
        oos_rows = np.concatenate([parts[s] for s in oos_combo])

        is_perf = objective(M[is_rows], periods_per_year)
        oos_perf = objective(M[oos_rows], periods_per_year)
        n_star = int(np.argmax(is_perf))

        # relative OOS rank of the IS-best strategy in (0,1), ties -> average rank
        order = np.argsort(oos_perf)                      # ascending
        rank_of = np.empty(N)
        rank_of[order] = np.arange(1, N + 1)
        # average-rank for ties on the selected value
        tie = oos_perf == oos_perf[n_star]
        w = rank_of[tie].mean() / (N + 1)                 # in (0,1)
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(np.log(w / (1 - w)))
        ranks.append(w)
        selected.append(n_star)
        oos_sel.append(oos_perf[n_star])

    logits = np.asarray(logits)
    pbo = float(np.mean(logits <= 0.0))
    return PBOResult(
        pbo=pbo, n_splits=len(logits), n_strategies=N, S=S,
        logits=logits, oos_relative_ranks=np.asarray(ranks),
        is_selected=np.asarray(selected), oos_performance_of_selected=np.asarray(oos_sel),
        median_oos_of_selected=float(np.median(oos_sel)),
        prob_oos_loss=float(np.mean(np.asarray(oos_sel) < 0.0)),
    )
