"""
Deployment-validation regression reference.

Single source of truth for the *reference strategy* deployment run. Both the
golden-baseline generator (``regenerate_golden``) and the pytest regression
test import ``compute_reference_metrics`` from here, so the numbers under test
are produced by exactly the same code path as the notebook
``11_deployment_report.ipynb``.

Reference strategy inputs (Project 05 risk-engine final export):
  experiments/completed/exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv
  experiments/completed/exp_005_risk_engine_final/final_daily_weights.csv
Per-asset OHLCV (for the real liquidity / capacity model):
  data/raw/project_04_universe/*.csv

Read-only with respect to the repo: this module never writes anything. The
golden JSON is written only by the explicit ``regenerate_golden`` entry point.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

# quant-lab repo root: tests/ -> project_06_failure_analysis/ -> research/ -> root
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.deployment import run_deployment_validation
from src.analysis.deployment_stress import capacity_analysis
from src.analysis.liquidity import (
    load_price_volume,
    daily_dollar_volume,
    average_daily_volume,
    capacity_ceiling,
)
from src.analysis.turnover import summarize_turnover

EXP_DIR = ROOT / "experiments/completed/exp_005_risk_engine_final"
UNIVERSE_DIR = ROOT / "data/raw/project_04_universe"
GOLDEN_PATH = (
    ROOT
    / "research/project_06_failure_analysis/results/deployment_reference_metrics.json"
)

# Sweep grids — identical to notebook 11.
TRANSACTION_COSTS = [0, 2, 5, 10, 20, 50]
REBALANCE_FREQUENCIES = [1, 2, 5, 10, "weekly"]
CAPITAL_LEVELS = [10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000]


def load_reference_strategy():
    """Return (returns, weights, equity) for the reference strategy."""
    ret_df = pd.read_csv(EXP_DIR / "final_weighted_multi_strategy_portfolio_dd.csv")
    weights_long = pd.read_csv(EXP_DIR / "final_daily_weights.csv", parse_dates=["Date"])

    weights = (
        weights_long.pivot(index="Date", columns="Ticker", values="Weight")
        .sort_index()
        .fillna(0.0)
    )
    dates = weights.index
    assert len(dates) == len(ret_df), (len(dates), len(ret_df))

    returns = pd.Series(ret_df["portfolio_return"].to_numpy(), index=dates, name="returns")
    equity = pd.Series(ret_df["equity_curve"].to_numpy(), index=dates, name="equity")
    return returns, weights, equity


def compute_reference_metrics() -> dict:
    """Run the full deployment validation on the reference strategy and return
    a flat dict of the key metrics that must stay stable across code changes."""
    returns, weights, equity = load_reference_strategy()

    result = run_deployment_validation(
        returns=returns,
        weights=weights,
        equity=equity,
        transaction_costs=TRANSACTION_COSTS,
        rebalance_frequencies=REBALANCE_FREQUENCIES,
    )

    turnover = summarize_turnover(result["turnover"])
    cost_stress = result["transaction_cost_stress"].set_index("Cost bps")
    # "Rebalance Frequency" mixes ints and the string "weekly" -> object dtype,
    # so key it by string representation for a stable lookup.
    rebalance = result["rebalance_analysis"].copy()
    rebalance_mean_turnover = (
        rebalance.assign(_key=rebalance["Rebalance Frequency"].astype(str))
        .set_index("_key")["Mean Turnover"]
    )

    # Real liquidity / capacity model (Daily Volume -> ADV -> participation).
    close, volume = load_price_volume(list(weights.columns), data_dir=UNIVERSE_DIR)
    adv = average_daily_volume(daily_dollar_volume(close, volume), window=20)
    capacity = capacity_analysis(
        returns=returns,
        weights=weights,
        capital_levels=CAPITAL_LEVELS,
        adv=adv,
    ).set_index("Capital")
    ceiling = capacity_ceiling(weights, adv, participation_cap=0.10)

    return {
        "n_days": int(len(returns)),
        "n_assets": int(weights.shape[1]),
        # Gross (0 bps) headline metrics
        "gross_0bps": {
            k: float(cost_stress.loc[0, k]) for k in ("Sharpe", "CAGR", "MDD", "Calmar")
        },
        # Deployed base case (10 bps)
        "net_10bps": {
            k: float(cost_stress.loc[10, k]) for k in ("Sharpe", "CAGR", "MDD", "Calmar")
        },
        # Turnover profile (daily rebalance)
        "turnover": {k: float(turnover[k]) for k in ("mean", "median", "max", "p95")},
        # Turnover under coarser rebalancing
        "turnover_by_freq_mean": {
            str(f): float(rebalance_mean_turnover[str(f)])
            for f in REBALANCE_FREQUENCIES
        },
        # Capacity at $1M and $5M under the real market-impact model
        "capacity_1m": {
            k: float(capacity.loc[1_000_000, k])
            for k in ("Sharpe", "CAGR", "MDD", "Mean Participation")
        },
        "capacity_5m": {
            k: float(capacity.loc[5_000_000, k]) for k in ("Sharpe", "CAGR", "MDD")
        },
        # Participation-cap capacity ceiling (10% of ADV)
        "capacity_ceiling_10pct": {
            k: float(ceiling[k])
            for k in ("median_capital", "p05_capital", "min_capital")
        },
    }


def regenerate_golden() -> dict:
    """Compute metrics and (over)write the golden baseline JSON. Explicit,
    manual entry point — never called by the test."""
    metrics = compute_reference_metrics()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    return metrics


if __name__ == "__main__":
    m = regenerate_golden()
    print(f"Wrote golden baseline -> {GOLDEN_PATH}")
    print(json.dumps(m, indent=2, sort_keys=True))
