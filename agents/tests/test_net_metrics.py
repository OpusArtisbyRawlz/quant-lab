"""Tests for agents/experiment_runner/net_metrics.py."""

import numpy as np
import pandas as pd
import pytest

from agents.experiment_runner.net_metrics import build_metric_bundle
from agents.experiment_runner.cost_model import CostConfig


def _weighted_panel(n_dates=40, n_tickers=6, seed=0):
    """A simple long/short weighted panel with daily rebalancing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="B")
    tickers = [f"T{i}" for i in range(n_tickers)]
    rows = []
    for d in dates:
        signal = rng.normal(size=n_tickers)
        order = np.argsort(signal)
        w = np.zeros(n_tickers)
        w[order[: n_tickers // 3]] = -1.0
        w[order[-n_tickers // 3:]] = 1.0
        s = np.abs(w).sum()
        if s > 0:
            w = w / s
        for tk, wi in zip(tickers, w):
            rows.append({"Date": d, "ticker": tk, "weight": wi})
    panel = pd.DataFrame(rows)
    gross = panel.groupby("Date").apply(
        lambda g: float((g["weight"] * rng.normal(0.001, 0.01, len(g))).sum())
    )
    return panel, gross


def test_bundle_preserves_flat_gross_keys():
    panel, gross = _weighted_panel()
    b = build_metric_bundle(panel, gross, CostConfig())
    for k in ("sharpe", "mdd", "cagr", "vol", "calmar"):
        assert k in b


def test_bundle_has_net_block_with_all_keys():
    panel, gross = _weighted_panel()
    b = build_metric_bundle(panel, gross, CostConfig())
    assert "net" in b
    for k in ("sharpe", "mdd", "cagr", "vol", "calmar"):
        assert k in b["net"]


def test_bundle_has_both_turnover_forms():
    panel, gross = _weighted_panel()
    b = build_metric_bundle(panel, gross, CostConfig())
    assert "turnover_annualized" in b
    assert "turnover_average_period" in b
    assert b["turnover_average_period"] is not None
    assert b["turnover_annualized"] is not None


def test_bundle_has_cost_fields():
    panel, gross = _weighted_panel()
    b = build_metric_bundle(panel, gross, CostConfig())
    assert "transaction_cost_annualized" in b
    assert "slippage_annualized" in b
    assert "cost_drag_annualized" in b


def test_zero_cost_net_equals_gross():
    panel, gross = _weighted_panel()
    b = build_metric_bundle(panel, gross, CostConfig.zero())
    assert b["net"]["sharpe"] == pytest.approx(b["sharpe"])
    assert b["net"]["cagr"] == pytest.approx(b["cagr"])


def test_positive_cost_lowers_net_sharpe():
    panel, gross = _weighted_panel(seed=3)
    free = build_metric_bundle(panel, gross, CostConfig.zero())
    costly = build_metric_bundle(panel, gross, CostConfig(commission_bps=20, spread_bps=20, slippage_bps=20))
    # With heavy costs and daily turnover, net Sharpe must not exceed gross.
    assert costly["net"]["sharpe"] <= free["net"]["sharpe"] + 1e-9


def test_turnover_annualized_is_average_times_periods():
    panel, gross = _weighted_panel()
    b = build_metric_bundle(panel, gross, CostConfig(periods_per_year=252))
    assert b["turnover_annualized"] == pytest.approx(
        b["turnover_average_period"] * 252, rel=1e-6
    )
