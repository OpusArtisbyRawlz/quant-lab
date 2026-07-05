"""
Reusable robustness experiment for a single market.

This module runs the combined rebalance-frequency x transaction-cost
robustness grid for one market and returns a tidy results table. It only
*orchestrates* existing building blocks (data loader, strategy stack,
turnover analytics, performance metrics) — it does not change any strategy
construction logic, and it performs no file I/O or plotting.
"""

from typing import Sequence, Union

import numpy as np
import pandas as pd

from src.data.loader import download_market_data
from src.pipelines.strategy_returns import build_strategy_return_stack
from src.analysis.turnover import compute_turnover
from src.utils.metrics import (
    sharpe_ratio,
    max_drawdown,
    annualized_return,
)

RebalanceFrequency = Union[int, str]


def run_market_robustness(
    market_spec: dict,
    target_vol: float,
    rebalance_frequencies: Sequence[RebalanceFrequency],
    transaction_costs: Sequence[float],
) -> pd.DataFrame:
    """
    Run the rebalance-frequency x transaction-cost robustness grid for one market.

    Parameters
    ----------
    market_spec : dict
        Specification of the market to test. Recognised keys:

        ``"config"`` (required)
            A market config dict consumed by
            :func:`src.data.loader.download_market_data` (e.g. an entry of
            ``MARKET_CONFIGS``).
        ``"signals"`` (required)
            List of signal names passed to
            :func:`~src.pipelines.strategy_returns.build_strategy_return_stack`.
        ``"name"`` (optional)
            Human-readable market label for the output. Falls back to
            ``config["name"]`` and then ``"Unknown"``.
    target_vol : float
        Annualised volatility target forwarded to the strategy stack.
    rebalance_frequencies : sequence of int or str
        Rebalance frequencies to sweep (e.g. ``[1, 5, "weekly"]``). Each value
        is passed straight through to ``build_strategy_return_stack`` as
        ``rebalance_frequency``.
    transaction_costs : sequence of float
        One-way transaction costs in basis points (e.g. ``[0.0, 5.0, 10.0]``).
        Converted to a decimal rate as ``cost_bps / 10000`` and charged on the
        per-period one-way turnover.

    Returns
    -------
    pd.DataFrame
        One row per ``(rebalance_frequency, transaction_cost)`` combination with
        columns: ``Market``, ``Signal Combo``, ``Rebalance Frequency``,
        ``Cost bps``, ``Sharpe``, ``MDD``, ``CAGR``, ``Calmar``,
        ``Mean Turnover``, ``Median Turnover``, ``P95 Turnover`` and
        ``% Trading Days``.
    """
    config = market_spec["config"]
    signals = list(market_spec["signals"])
    market_name = market_spec.get("name") or config.get("name", "Unknown")
    signal_combo = " + ".join(signals)

    market_data = download_market_data(config)

    rows: list[dict] = []

    for freq in rebalance_frequencies:
        stack = build_strategy_return_stack(
            market_data,
            signal_names=signals,
            target_vol=target_vol,
            rebalance_frequency=freq,
        )

        returns = stack["dd_vol_ret"]

        weights = (
            stack["panel"]
            .pivot(index="Date", columns="ticker", values="weight")
            .fillna(0)
        )

        turnover = compute_turnover(weights)

        # Turnover summary stats depend only on the weight path, not on cost.
        mean_turnover = float(turnover.mean())
        median_turnover = float(turnover.median())
        p95_turnover = float(np.nanpercentile(turnover, 95)) if len(turnover) else np.nan
        pct_trading_days = (
            float((turnover > 0).mean() * 100.0) if len(turnover) else np.nan
        )

        aligned_turnover = turnover.reindex(returns.index).fillna(0)

        for cost_bps in transaction_costs:
            cost_rate = cost_bps / 10000
            net_returns = returns - aligned_turnover * cost_rate

            equity = (1 + net_returns).cumprod()
            cagr = annualized_return(net_returns)
            mdd = max_drawdown(equity)
            calmar = cagr / abs(mdd) if mdd not in (0, np.nan) and mdd else np.nan

            rows.append(
                {
                    "Market": market_name,
                    "Signal Combo": signal_combo,
                    "Rebalance Frequency": str(freq),
                    "Cost bps": cost_bps,
                    "Sharpe": sharpe_ratio(net_returns),
                    "MDD": mdd,
                    "CAGR": cagr,
                    "Calmar": calmar,
                    "Mean Turnover": mean_turnover,
                    "Median Turnover": median_turnover,
                    "P95 Turnover": p95_turnover,
                    "% Trading Days": pct_trading_days,
                }
            )

    return pd.DataFrame(rows)
