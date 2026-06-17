"""Tests for agents/experiment_runner/cost_model.py."""

import numpy as np
import pandas as pd
import pytest

from agents.experiment_runner.cost_model import (
    CostConfig,
    compute_turnover,
    transaction_costs,
    slippage_costs,
    apply_costs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _panel(weights_by_date: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Build a long panel from {date: {ticker: weight}}."""
    rows = []
    for date, wd in weights_by_date.items():
        for ticker, w in wd.items():
            rows.append({"Date": pd.Timestamp(date), "ticker": ticker, "weight": w})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# CostConfig
# ---------------------------------------------------------------------------

def test_config_loads_from_default_toml():
    cfg = CostConfig.load()
    assert cfg.commission_bps >= 0
    assert cfg.periods_per_year == 252


def test_zero_config_is_frictionless():
    cfg = CostConfig.zero()
    assert cfg.commission_bps == 0
    assert cfg.spread_bps == 0
    assert cfg.slippage_bps == 0
    assert cfg.trading_cost_bps == 0


def test_trading_cost_bps_is_commission_plus_spread():
    cfg = CostConfig(commission_bps=1.0, spread_bps=2.0, slippage_bps=5.0)
    assert cfg.trading_cost_bps == 3.0


# ---------------------------------------------------------------------------
# Turnover
# ---------------------------------------------------------------------------

def test_turnover_first_period_is_half_gross_weight():
    # Entering from flat: 0.5 * sum|w| = 0.5 * (0.5 + 0.5) = 0.5
    panel = _panel({"2020-01-01": {"A": 0.5, "B": -0.5}})
    t = compute_turnover(panel)
    assert t.iloc[0] == pytest.approx(0.5)


def test_turnover_zero_when_weights_constant():
    panel = _panel({
        "2020-01-01": {"A": 0.5, "B": -0.5},
        "2020-01-02": {"A": 0.5, "B": -0.5},
    })
    t = compute_turnover(panel)
    assert t.iloc[1] == pytest.approx(0.0)


def test_turnover_full_when_book_flips():
    panel = _panel({
        "2020-01-01": {"A": 0.5, "B": -0.5},
        "2020-01-02": {"A": -0.5, "B": 0.5},
    })
    t = compute_turnover(panel)
    # 0.5 * (|−0.5−0.5| + |0.5−(−0.5)|) = 0.5 * (1 + 1) = 1.0
    assert t.iloc[1] == pytest.approx(1.0)


def test_turnover_empty_panel_returns_empty():
    assert compute_turnover(pd.DataFrame()).empty


def test_turnover_missing_columns_returns_empty():
    df = pd.DataFrame({"Date": [1], "foo": [2]})
    assert compute_turnover(df).empty


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------

def test_transaction_cost_scales_with_turnover():
    cfg = CostConfig(commission_bps=1.0, spread_bps=1.0, slippage_bps=0.0)
    turnover = pd.Series([1.0, 0.5])
    tx = transaction_costs(turnover, cfg)
    # 2 bps * turnover
    assert tx.iloc[0] == pytest.approx(2e-4)
    assert tx.iloc[1] == pytest.approx(1e-4)


def test_slippage_scales_with_turnover():
    cfg = CostConfig(commission_bps=0.0, spread_bps=0.0, slippage_bps=4.0)
    turnover = pd.Series([1.0])
    assert slippage_costs(turnover, cfg).iloc[0] == pytest.approx(4e-4)


def test_apply_costs_net_le_gross_under_positive_costs():
    gross = pd.Series([0.01, 0.01, 0.01], index=pd.date_range("2020-01-01", periods=3))
    turnover = pd.Series([1.0, 1.0, 1.0], index=gross.index)
    cfg = CostConfig(commission_bps=5.0, spread_bps=5.0, slippage_bps=5.0)
    net, tx, slip = apply_costs(gross, turnover, cfg)
    assert (net <= gross).all()
    assert (tx > 0).all()
    assert (slip > 0).all()


def test_apply_costs_zero_cost_identity():
    gross = pd.Series([0.01, -0.02, 0.03], index=pd.date_range("2020-01-01", periods=3))
    turnover = pd.Series([1.0, 1.0, 1.0], index=gross.index)
    net, tx, slip = apply_costs(gross, turnover, CostConfig.zero())
    pd.testing.assert_series_equal(net, gross, check_names=False)
    assert (tx == 0).all()
    assert (slip == 0).all()


def test_apply_costs_missing_turnover_incurs_zero_cost():
    gross = pd.Series([0.01, 0.02], index=pd.date_range("2020-01-01", periods=2))
    net, tx, slip = apply_costs(gross, pd.Series(dtype=float), CostConfig())
    pd.testing.assert_series_equal(net, gross, check_names=False)
