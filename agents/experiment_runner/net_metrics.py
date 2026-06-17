"""
net_metrics.py — assemble the Milestone 5 gross + net metric bundle.

This module is the single place that combines:
  * gross metrics      (existing compute_metrics — unchanged keys)
  * net metrics        (compute_metrics on the cost-adjusted series)
  * turnover figures   (annualised + average-per-period)
  * estimated costs    (annualised transaction cost + slippage)

It deliberately reuses ``compute_metrics`` from metrics_writer for BOTH the
gross and net series so there is exactly one metric implementation.  The output
preserves the flat gross keys (sharpe/mdd/cagr/vol/calmar) for backwards
compatibility and nests net metrics under ``metrics["net"]``.

Output schema
-------------
{
    "sharpe": ..., "mdd": ..., "cagr": ..., "vol": ..., "calmar": ...,   # GROSS
    "net": {"sharpe": ..., "mdd": ..., "cagr": ..., "vol": ..., "calmar": ...},
    "turnover_annualized": ...,
    "turnover_average_period": ...,
    "transaction_cost_annualized": ...,
    "slippage_annualized": ...,
    "cost_drag_annualized": ...,
    # robustness keys are merged in by the caller (runner) from robustness.py
}
"""

from __future__ import annotations

import logging

import pandas as pd

from agents.experiment_runner.metrics_writer import compute_metrics, _nan_to_none
from agents.experiment_runner.cost_model import CostConfig, compute_turnover, apply_costs

log = logging.getLogger(__name__)


def build_metric_bundle(
    panel: pd.DataFrame,
    gross_returns: pd.Series,
    cfg: CostConfig,
    *,
    periods_per_year: int = 252,
) -> dict:
    """
    Build the full gross + net + turnover/cost metric dict.

    Parameters
    ----------
    panel : DataFrame
        Weighted panel (output of apply_signal_combo) — used for turnover.
    gross_returns : pd.Series
        Daily gross portfolio returns, indexed by date.
    cfg : CostConfig
        Cost assumptions.
    periods_per_year : int
        Annualisation basis for metrics and turnover/cost figures.

    Returns
    -------
    dict
        Structured metrics.  Flat gross keys preserved for backwards
        compatibility; net metrics nested under "net".
    """
    # ── Gross metrics (unchanged behaviour) ───────────────────────────────
    gross = compute_metrics(gross_returns, periods_per_year)

    # ── Turnover + net returns ────────────────────────────────────────────
    turnover = compute_turnover(panel)
    net_returns, tx_cost, slippage = apply_costs(gross_returns, turnover, cfg)

    net = compute_metrics(net_returns, periods_per_year)

    # ── Turnover figures ──────────────────────────────────────────────────
    avg_turnover = float(turnover.mean()) if not turnover.empty else None
    turnover_annualized = (
        _nan_to_none(avg_turnover * periods_per_year) if avg_turnover is not None else None
    )

    # ── Cost figures (annualised average per-period drag) ─────────────────
    avg_tx = float(tx_cost.mean()) if not tx_cost.empty else None
    avg_slip = float(slippage.mean()) if not slippage.empty else None
    tx_annual = _nan_to_none(avg_tx * periods_per_year) if avg_tx is not None else None
    slip_annual = _nan_to_none(avg_slip * periods_per_year) if avg_slip is not None else None
    cost_drag = (
        _nan_to_none((avg_tx + avg_slip) * periods_per_year)
        if avg_tx is not None and avg_slip is not None
        else None
    )

    bundle = dict(gross)  # flat gross keys: sharpe, mdd, cagr, vol, calmar
    bundle["net"] = net
    bundle["turnover_annualized"] = turnover_annualized
    bundle["turnover_average_period"] = _nan_to_none(avg_turnover) if avg_turnover is not None else None
    bundle["transaction_cost_annualized"] = tx_annual
    bundle["slippage_annualized"] = slip_annual
    bundle["cost_drag_annualized"] = cost_drag

    return bundle
