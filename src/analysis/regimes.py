"""
Regime-conditional performance analytics.

The risk engine in this repo is drawdown-centric, so regimes here are defined by
the portfolio's own drawdown state. Given a return series (and optionally its
equity curve) these helpers label each day with a regime and summarise
performance within each regime. Pure functions — no I/O, no plotting.
"""

from typing import Sequence

import pandas as pd

from src.risk.drawdown import compute_drawdown
from src.utils.metrics import (
    sharpe_ratio,
    max_drawdown,
    annualized_return,
    annualized_volatility,
)


def classify_drawdown_regime(
    equity: pd.Series,
    thresholds: Sequence[float] = (-0.10, -0.20),
    labels: Sequence[str] = ("Normal", "Correction", "Bear"),
) -> pd.Series:
    """
    Label each date by the portfolio's current drawdown state.

    With the default thresholds: drawdown above -10% is ``"Normal"``, between
    -10% and -20% is ``"Correction"``, and at or below -20% is ``"Bear"``.

    Parameters
    ----------
    equity : pd.Series
        Equity curve (growth of 1).
    thresholds : sequence of float, default (-0.10, -0.20)
        Descending drawdown cut points; ``len(labels) == len(thresholds) + 1``.
    labels : sequence of str
        Regime names from mildest to most severe.

    Returns
    -------
    pd.Series
        Regime label per date.
    """
    if len(labels) != len(thresholds) + 1:
        raise ValueError("labels must have exactly one more entry than thresholds")

    dd = compute_drawdown(pd.Series(equity).astype(float))

    regime = pd.Series(labels[0], index=dd.index)
    for thresh, label in zip(thresholds, labels[1:]):
        regime[dd <= thresh] = label

    return regime


def regime_analysis(
    returns: pd.Series,
    equity: pd.Series = None,
    thresholds: Sequence[float] = (-0.10, -0.20),
    labels: Sequence[str] = ("Normal", "Correction", "Bear"),
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """
    Summarise performance conditional on drawdown regime.

    Parameters
    ----------
    returns : pd.Series
        Daily return series.
    equity : pd.Series, optional
        Equity curve used to define regimes. If omitted it is derived from
        ``returns`` as ``(1 + returns).cumprod()``.
    thresholds, labels :
        Forwarded to :func:`classify_drawdown_regime`.
    periods_per_year : int, default 252
        Annualisation factor.

    Returns
    -------
    pd.DataFrame
        One row per regime with columns ``Regime``, ``Days``, ``Ann Return``,
        ``Ann Vol``, ``Sharpe`` and ``MDD``.
    """
    returns = pd.Series(returns).astype(float)

    if equity is None:
        equity = (1 + returns.fillna(0)).cumprod()
    equity = pd.Series(equity).astype(float).reindex(returns.index)

    regime = classify_drawdown_regime(equity, thresholds=thresholds, labels=labels)

    rows = []
    for label in labels:
        mask = regime == label
        r = returns[mask]
        if r.empty:
            rows.append(
                {
                    "Regime": label, "Days": 0, "Ann Return": float("nan"),
                    "Ann Vol": float("nan"), "Sharpe": float("nan"),
                    "MDD": float("nan"),
                }
            )
            continue

        eq = (1 + r).cumprod()
        rows.append(
            {
                "Regime": label,
                "Days": int(mask.sum()),
                "Ann Return": annualized_return(r, periods_per_year),
                "Ann Vol": annualized_volatility(r, periods_per_year),
                "Sharpe": sharpe_ratio(r, periods_per_year),
                "MDD": max_drawdown(eq),
            }
        )

    return pd.DataFrame(rows)
