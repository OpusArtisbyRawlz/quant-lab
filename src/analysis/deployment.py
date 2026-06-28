"""
Deployment-validation analytics.

Two kinds of helper live here:

* **Selection helpers** (:func:`select_best_per_group`,
  :func:`pivot_metric_table`) turn a parameter-grid results table into a
  deployment decision matrix.
* **Validation helpers** (:func:`transaction_cost_stress`,
  :func:`rebalance_analysis`, :func:`run_deployment_validation`) take the
  *already-computed* outputs of a deployed strategy (its return series, weight
  panel and equity curve) and stress-test them.

:func:`run_deployment_validation` is the single orchestrator a deployment
notebook should call: it composes existing building blocks
(:func:`src.analysis.turnover.compute_turnover`, the cost / rebalance helpers
below, :func:`src.analysis.rolling.rolling_metrics` and
:func:`src.analysis.regimes.regime_analysis`) and returns a dict of tidy
tables. No I/O, no plotting, no strategy reconstruction.
"""

from typing import Sequence, Union

import numpy as np
import pandas as pd

from src.analysis.turnover import compute_turnover, summarize_turnover
from src.analysis.rolling import rolling_metrics
from src.analysis.regimes import regime_analysis
from src.portfolio.rebalance import apply_rebalance_frequency, weights_to_wide
from src.utils.metrics import (
    sharpe_ratio,
    max_drawdown,
    annualized_return,
)

RebalanceFrequency = Union[int, str]


def select_best_per_group(
    df: pd.DataFrame,
    group_cols: Sequence[str],
    score_col: str = "Sharpe",
    maximize: bool = True,
) -> pd.DataFrame:
    """
    Pick the single best row within each group.

    For every unique combination of ``group_cols`` this returns the row whose
    ``score_col`` is the best (largest when ``maximize`` is ``True``, smallest
    otherwise). Ties are broken by the original row order within the group.

    Parameters
    ----------
    df : pd.DataFrame
        Tidy results table (e.g. one row per parameter combination).
    group_cols : sequence of str
        Columns that define each group (e.g. ``["Market", "Cost bps"]``).
    score_col : str, default "Sharpe"
        Column to optimise.
    maximize : bool, default True
        If ``True`` keep the highest ``score_col`` per group, else the lowest.

    Returns
    -------
    pd.DataFrame
        One row per group, with all original columns preserved.
    """
    group_cols = list(group_cols)

    ordered = df.sort_values(
        [*group_cols, score_col],
        ascending=[True] * len(group_cols) + [not maximize],
    )

    return ordered.groupby(group_cols, as_index=False).first()


def pivot_metric_table(
    df: pd.DataFrame,
    index: str,
    columns: str,
    value_col: str,
) -> pd.DataFrame:
    """
    Reshape a long results table into a wide decision matrix.

    Thin, intent-revealing wrapper around :meth:`pandas.DataFrame.pivot` used to
    build deployment summary tables such as ``(Cost bps x Market)`` showing the
    chosen rebalance frequency in each cell.

    Parameters
    ----------
    df : pd.DataFrame
        Typically the output of :func:`select_best_per_group`.
    index, columns : str
        Column names to use for the row and column axes.
    value_col : str
        Column whose values populate the cells.

    Returns
    -------
    pd.DataFrame
        Wide ``index x columns`` table of ``value_col``.
    """
    return df.pivot(index=index, columns=columns, values=value_col)


def transaction_cost_stress(
    returns: pd.Series,
    turnover: pd.Series,
    transaction_costs: Sequence[float],
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """
    Stress a return series against a sweep of one-way transaction costs.

    Net returns are charged as ``returns - turnover * (cost_bps / 10000)`` on the
    per-period one-way turnover, mirroring the convention used by
    :func:`src.analysis.robustness.run_market_robustness` — but operating on an
    *already-computed* return + turnover pair rather than rebuilding a strategy.

    Parameters
    ----------
    returns : pd.Series
        Daily gross (pre-cost) return series.
    turnover : pd.Series
        Daily one-way turnover (e.g. from
        :func:`src.analysis.turnover.compute_turnover`). Re-aligned to
        ``returns`` and zero-filled.
    transaction_costs : sequence of float
        One-way costs in basis points (e.g. ``[0, 5, 10]``).
    periods_per_year : int, default 252
        Annualisation factor.

    Returns
    -------
    pd.DataFrame
        One row per cost level with columns ``Cost bps``, ``Sharpe``, ``MDD``,
        ``CAGR``, ``Calmar`` and ``Mean Turnover``.
    """
    returns = pd.Series(returns).astype(float)
    aligned = pd.Series(turnover).reindex(returns.index).fillna(0.0)

    rows = []
    for cost_bps in transaction_costs:
        cost_rate = cost_bps / 10000.0
        net = returns - aligned * cost_rate

        equity = (1 + net).cumprod()
        cagr = annualized_return(net, periods_per_year)
        mdd = max_drawdown(equity)
        calmar = cagr / abs(mdd) if mdd and mdd == mdd else np.nan

        rows.append(
            {
                "Cost bps": cost_bps,
                "Sharpe": sharpe_ratio(net, periods_per_year),
                "MDD": mdd,
                "CAGR": cagr,
                "Calmar": calmar,
                "Mean Turnover": float(aligned.mean()),
            }
        )

    return pd.DataFrame(rows)


def rebalance_analysis(
    weights: pd.DataFrame,
    rebalance_frequencies: Sequence[RebalanceFrequency],
    date_col: str = "Date",
    asset_col: str = "ticker",
) -> pd.DataFrame:
    """
    Summarise how turnover responds to the rebalance frequency.

    For each frequency the deployed weight path is re-held at that cadence using
    :func:`src.portfolio.rebalance.apply_rebalance_frequency` (the single source
    of carry-forward logic), then turnover is recomputed and summarised. This
    reuses existing building blocks rather than reimplementing them.

    Parameters
    ----------
    weights : pd.DataFrame
        Wide weight matrix indexed by date, columns are assets (as consumed by
        :func:`src.analysis.turnover.compute_turnover`).
    rebalance_frequencies : sequence of int or str
        Frequencies to sweep, e.g. ``[1, 5, "weekly"]``.
    date_col, asset_col : str
        Names used when round-tripping the wide matrix through the long-format
        rebalance helper.

    Returns
    -------
    pd.DataFrame
        One row per frequency with columns ``Rebalance Frequency``,
        ``Mean Turnover``, ``Median Turnover``, ``Max Turnover`` and
        ``P95 Turnover``.
    """
    wide = weights.copy()
    wide.index = wide.index.rename(date_col)

    long = wide.reset_index().melt(
        id_vars=date_col, var_name=asset_col, value_name="weight"
    )

    rows = []
    for freq in rebalance_frequencies:
        held_long = apply_rebalance_frequency(
            long,
            rebalance_frequency=freq,
            date_col=date_col,
            asset_col=asset_col,
            weight_col="weight",
        )
        held_wide = weights_to_wide(
            held_long, date_col=date_col, asset_col=asset_col, weight_col="weight"
        )

        summary = summarize_turnover(compute_turnover(held_wide))

        rows.append(
            {
                "Rebalance Frequency": str(freq),
                "Mean Turnover": summary["mean"],
                "Median Turnover": summary["median"],
                "Max Turnover": summary["max"],
                "P95 Turnover": summary["p95"],
            }
        )

    return pd.DataFrame(rows)


def run_deployment_validation(
    returns: pd.Series,
    weights: pd.DataFrame,
    equity: pd.Series,
    transaction_costs: Sequence[float],
    rebalance_frequencies: Sequence[RebalanceFrequency],
    rolling_window: int = 252,
    periods_per_year: int = 252,
) -> dict:
    """
    Run the full deployment-validation battery on a deployed strategy's outputs.

    This is a pure orchestrator: it does not reconstruct or re-run any strategy,
    it only composes existing analytics over the supplied series. A deployment
    notebook should build ``returns`` / ``weights`` / ``equity`` once (via the
    existing strategy pipeline) and hand them here.

    Parameters
    ----------
    returns : pd.Series
        Daily portfolio return series.
    weights : pd.DataFrame
        Wide weight matrix indexed by date, columns are assets.
    equity : pd.Series
        Equity curve (growth of 1) for the same dates as ``returns``.
    transaction_costs : sequence of float
        One-way transaction costs in basis points to stress.
    rebalance_frequencies : sequence of int or str
        Rebalance frequencies to sweep.
    rolling_window : int, default 252
        Window for :func:`src.analysis.rolling.rolling_metrics`.
    periods_per_year : int, default 252
        Annualisation factor used throughout.

    Returns
    -------
    dict
        ``{
            "turnover": pd.Series,
            "transaction_cost_stress": pd.DataFrame,
            "rebalance_analysis": pd.DataFrame,
            "rolling_metrics": pd.DataFrame,
            "regime_analysis": pd.DataFrame,
        }``
    """
    turnover = compute_turnover(weights)

    return {
        "turnover": turnover,
        "transaction_cost_stress": transaction_cost_stress(
            returns, turnover, transaction_costs, periods_per_year=periods_per_year
        ),
        "rebalance_analysis": rebalance_analysis(
            weights, rebalance_frequencies
        ),
        "rolling_metrics": rolling_metrics(
            returns, window=rolling_window, periods_per_year=periods_per_year
        ),
        "regime_analysis": regime_analysis(
            returns, equity=equity, periods_per_year=periods_per_year
        ),
    }
