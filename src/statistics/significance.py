"""
Test statistics and multiple-testing corrections for Project 07.

When many hypotheses/configurations are evaluated, per-hypothesis significance is
misleading: some cross any fixed threshold by chance. This module provides the
base test statistics and the family-level corrections that control either the
family-wise error rate (FWER) or the false-discovery rate (FDR):

- **Benjamini–Hochberg** (FDR control) — the default for research screening.
- **Bonferroni** and **Holm–Bonferroni** (FWER control) — stricter.

It also provides the finite-sample **Sharpe-ratio standard error / t-statistic**
(Lo, 2002), which corrects for autocorrelation and non-normality of returns.

Scaffold only — all bodies raise ``NotImplementedError``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MultipleTestingResult:
    """Result of a family-level multiple-testing correction.

    Attributes
    ----------
    method
        Correction applied (``"benjamini_hochberg"``, ``"bonferroni"``,
        ``"holm"``).
    alpha
        Target error level (FDR level or FWER).
    pvalues
        Original per-hypothesis p-values (input order).
    adjusted_pvalues
        Corrected p-values (input order).
    rejected
        Boolean mask of hypotheses rejected at ``alpha`` (input order).
    n_significant
        Count of rejected hypotheses.
    """

    method: str
    alpha: float
    pvalues: np.ndarray
    adjusted_pvalues: np.ndarray
    rejected: np.ndarray
    n_significant: int


def sharpe_standard_error(
    returns: pd.Series,
    *,
    periods_per_year: int = 252,
) -> float:
    """Finite-sample standard error of the annualised Sharpe ratio (Lo, 2002).

    Accounts for the number of observations and the non-normality
    (skew/kurtosis) of the return distribution.

    Parameters
    ----------
    returns
        Daily return series.
    periods_per_year
        Annualisation factor.

    Returns
    -------
    float
        Standard error of the annualised Sharpe ratio.
    """
    raise NotImplementedError("Sharpe standard error not implemented (scaffold).")


def sharpe_tstat(
    returns: pd.Series,
    *,
    periods_per_year: int = 252,
) -> float:
    """t-statistic for the null that the true Sharpe ratio is zero.

    Parameters
    ----------
    returns
        Daily return series.
    periods_per_year
        Annualisation factor.

    Returns
    -------
    float
        The Sharpe t-statistic (estimate divided by :func:`sharpe_standard_error`).
    """
    raise NotImplementedError("Sharpe t-stat not implemented (scaffold).")


def _validate_pvalues_alpha(pvalues: np.ndarray, alpha: float) -> np.ndarray:
    """Shared validation for the family-level corrections. Returns a 1-D float array."""
    arr = np.asarray(pvalues, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError("pvalues must be non-empty")
    if not np.isfinite(arr).all():
        raise ValueError("pvalues must be finite (no NaN/Inf)")
    if arr.min() < 0.0 or arr.max() > 1.0:
        raise ValueError("pvalues must lie within [0, 1]")
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float, np.integer, np.floating))
        or not (0.0 < float(alpha) < 1.0)
    ):
        raise ValueError(f"alpha must be strictly in (0, 1), got {alpha!r}")
    return arr


def benjamini_hochberg(
    pvalues: np.ndarray,
    *,
    alpha: float = 0.05,
) -> MultipleTestingResult:
    """Benjamini–Hochberg false-discovery-rate correction.

    Pure function of the p-value vector (no strategy-specific logic). Computes the
    monotone step-up BH-adjusted p-values (q-values) and rejects hypotheses whose
    adjusted p-value is ``<= alpha``. Adjusted p-values and the rejection mask are
    returned in the **original input order**.

    Parameters
    ----------
    pvalues
        Per-hypothesis p-values (non-empty, finite, within ``[0, 1]``).
    alpha
        Target false-discovery rate, strictly in ``(0, 1)``.

    Returns
    -------
    MultipleTestingResult
        Adjusted p-values and rejection mask (input order).
    """
    arr = _validate_pvalues_alpha(pvalues, alpha)
    m = arr.size

    order = np.argsort(arr)                       # ascending
    ranks = np.arange(1, m + 1)
    ps_sorted = arr[order]

    # BH adjusted p-values: min over k>=i of (m/k)*p_(k), enforced monotone
    # non-decreasing in sorted order, then clipped to [0, 1].
    adj_sorted = np.minimum.accumulate((ps_sorted * m / ranks)[::-1])[::-1]
    adj_sorted = np.clip(adj_sorted, 0.0, 1.0)

    adjusted = np.empty(m, dtype=float)
    adjusted[order] = adj_sorted                  # restore original input order

    rejected = adjusted <= float(alpha)
    return MultipleTestingResult(
        method="benjamini_hochberg",
        alpha=float(alpha),
        pvalues=arr,
        adjusted_pvalues=adjusted,
        rejected=rejected,
        n_significant=int(rejected.sum()),
    )


def bonferroni(
    pvalues: np.ndarray,
    *,
    alpha: float = 0.05,
) -> MultipleTestingResult:
    """Bonferroni family-wise-error correction.

    Pure function of the p-value vector. Adjusted p-values are ``min(m * p_i, 1)``
    and a hypothesis is rejected where its adjusted p-value is ``<= alpha``.
    Everything is returned in the original input order.

    Parameters
    ----------
    pvalues
        Per-hypothesis p-values (non-empty, finite, within ``[0, 1]``).
    alpha
        Target family-wise error rate, strictly in ``(0, 1)``.

    Returns
    -------
    MultipleTestingResult
        Adjusted p-values and rejection mask (input order).
    """
    arr = _validate_pvalues_alpha(pvalues, alpha)
    m = arr.size

    adjusted = np.minimum(arr * m, 1.0)
    rejected = adjusted <= float(alpha)
    return MultipleTestingResult(
        method="bonferroni",
        alpha=float(alpha),
        pvalues=arr,
        adjusted_pvalues=adjusted,
        rejected=rejected,
        n_significant=int(rejected.sum()),
    )


def holm(
    pvalues: np.ndarray,
    *,
    alpha: float = 0.05,
) -> MultipleTestingResult:
    """Holm–Bonferroni step-down family-wise-error correction.

    Parameters
    ----------
    pvalues
        Per-hypothesis p-values.
    alpha
        Target family-wise error rate.

    Returns
    -------
    MultipleTestingResult
        Adjusted p-values and rejection mask.
    """
    raise NotImplementedError("Holm not implemented (scaffold).")
