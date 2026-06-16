"""
metrics_writer.py — compute performance metrics and write experiment artifacts.

This is the ONLY module in agents/ that imports from src/utils/metrics.
All metric computation delegates to that module — no duplication here.

Writes two files:
  metrics.json            — scalar metrics dict (sharpe, mdd, cagr, vol, calmar)
  strategy_comparison.csv — one row per strategy variant (supports multi-variant)
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pandas as pd

# src/ import — permitted for experiment_runner adapter modules
from src.utils.metrics import (
    annualized_return,
    annualized_volatility,
    max_drawdown,
    sharpe_ratio,
)

_STRATEGY_CSV_COLUMNS = ["Strategy", "Sharpe", "MDD", "CAGR", "Vol", "Calmar"]


def compute_metrics(
    portfolio_returns: pd.Series,
    periods_per_year: int = 252,
) -> dict[str, float | None]:
    """
    Compute standard portfolio metrics from a daily return series.

    Parameters
    ----------
    portfolio_returns : pd.Series
        Daily portfolio returns (not cumulative).
    periods_per_year : int
        Trading days per year for annualisation (default 252).

    Returns
    -------
    dict with keys: sharpe, mdd, cagr, vol, calmar.
    Values are float or None when the series is too short / degenerate.
    """
    returns = portfolio_returns.dropna()
    equity = (1 + returns).cumprod()

    sharpe = _nan_to_none(sharpe_ratio(returns, periods_per_year))
    mdd    = _nan_to_none(max_drawdown(equity))
    cagr   = _nan_to_none(annualized_return(returns, periods_per_year))
    vol    = _nan_to_none(annualized_volatility(returns, periods_per_year))

    calmar: float | None = None
    if cagr is not None and mdd is not None and mdd != 0:
        calmar = round(cagr / abs(mdd), 4)

    return {
        "sharpe": sharpe,
        "mdd":    mdd,
        "cagr":   cagr,
        "vol":    vol,
        "calmar": calmar,
    }


def write_metrics_json(metrics: dict, folder: Path) -> None:
    """Write metrics dict to metrics.json in the experiment folder."""
    path = folder / "metrics.json"
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def write_strategy_csv(
    variants: list[dict],
    folder: Path,
) -> None:
    """
    Write strategy_comparison.csv.

    Parameters
    ----------
    variants : list[dict]
        Each dict must have keys: Strategy, Sharpe, MDD, CAGR, Vol, Calmar.
        Any extra keys are appended as additional columns.
    folder : Path
        Experiment folder to write into.
    """
    if not variants:
        return

    # Collect all column names: standard first, then any extras
    extra_cols: list[str] = []
    for v in variants:
        for k in v:
            if k not in _STRATEGY_CSV_COLUMNS and k not in extra_cols:
                extra_cols.append(k)

    fieldnames = _STRATEGY_CSV_COLUMNS + extra_cols
    path = folder / "strategy_comparison.csv"

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for v in variants:
            row = {col: v.get(col, "") for col in fieldnames}
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nan_to_none(value: float) -> float | None:
    """Convert NaN/Inf to None for clean JSON serialisation."""
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
    except (TypeError, ValueError):
        return None
    return round(float(value), 6)
