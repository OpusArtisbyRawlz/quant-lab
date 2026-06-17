"""Tests for agents/experiment_runner/robustness.py."""

import numpy as np
import pandas as pd
import pytest

from agents.experiment_runner.robustness import (
    subperiod_sharpes,
    build_robustness_report,
    parameter_sensitivity,
    FLAG_SUBPERIOD,
    FLAG_PARAMETER,
    FLAG_COST,
)
from agents.experiment_runner.cost_model import CostConfig


# ---------------------------------------------------------------------------
# Subperiod
# ---------------------------------------------------------------------------

def test_subperiod_returns_n_values():
    r = pd.Series(np.random.default_rng(0).normal(0.001, 0.01, 90))
    out = subperiod_sharpes(r, n_splits=3)
    assert len(out) == 3


def test_subperiod_too_short_returns_empty():
    assert subperiod_sharpes(pd.Series([0.01]), n_splits=3) == []


# ---------------------------------------------------------------------------
# Flag logic
# ---------------------------------------------------------------------------

def test_cost_fragility_flag_when_net_collapses():
    # Strong gross Sharpe, net Sharpe near zero → cost fragility.
    net_returns = pd.Series(np.full(60, 0.00001))
    rep = build_robustness_report(
        net_returns=net_returns,
        gross_sharpe=2.0,
        net_sharpe=0.1,           # retains < 50% of gross
        sensitivity={"net_sharpe_spread": 0.0, "points": []},
    )
    assert FLAG_COST in rep["robustness_flags"]


def test_no_cost_fragility_when_net_retains_most_of_gross():
    net_returns = pd.Series(np.random.default_rng(1).normal(0.002, 0.005, 60))
    rep = build_robustness_report(
        net_returns=net_returns,
        gross_sharpe=1.0,
        net_sharpe=0.95,
        sensitivity={"net_sharpe_spread": 0.0, "points": []},
    )
    assert FLAG_COST not in rep["robustness_flags"]


def test_parameter_fragility_flag_on_large_spread():
    net_returns = pd.Series(np.random.default_rng(2).normal(0.001, 0.01, 60))
    rep = build_robustness_report(
        net_returns=net_returns,
        gross_sharpe=1.0,
        net_sharpe=1.0,
        sensitivity={"net_sharpe_spread": 5.0, "points": []},
        spread_tolerance=0.75,
    )
    assert FLAG_PARAMETER in rep["robustness_flags"]


def test_subperiod_instability_flag_on_sign_flip():
    # First half strongly positive, second half strongly negative.
    net_returns = pd.Series(np.concatenate([np.full(30, 0.01), np.full(30, -0.01)]))
    rep = build_robustness_report(
        net_returns=net_returns,
        gross_sharpe=0.5,
        net_sharpe=0.0,
        sensitivity={"net_sharpe_spread": 0.0, "points": []},
        n_splits=2,
    )
    assert FLAG_SUBPERIOD in rep["robustness_flags"]


def test_clean_strategy_has_no_flags():
    # Consistent positive returns, tiny spread, net ≈ gross.
    net_returns = pd.Series(np.full(90, 0.002))
    rep = build_robustness_report(
        net_returns=net_returns,
        gross_sharpe=3.0,
        net_sharpe=2.9,
        sensitivity={"net_sharpe_spread": 0.05, "points": [{"net_sharpe": 2.9}]},
    )
    assert rep["robustness_flags"] == []


def test_report_contains_expected_keys():
    net_returns = pd.Series(np.random.default_rng(4).normal(0.001, 0.01, 60))
    rep = build_robustness_report(
        net_returns=net_returns, gross_sharpe=1.0, net_sharpe=0.9,
        sensitivity={"net_sharpe_spread": 0.1, "points": []},
    )
    assert set(rep) == {"subperiod_sharpes", "parameter_sensitivity", "robustness_flags"}


# ---------------------------------------------------------------------------
# Parameter sensitivity grid
# ---------------------------------------------------------------------------

def test_parameter_sensitivity_probes_long_and_short():
    # Build a tiny base panel the real combo can consume.
    rng = np.random.default_rng(5)
    dates = pd.date_range("2020-01-01", periods=30, freq="B")
    tickers = [f"T{i}" for i in range(8)]
    rows = []
    for d in dates:
        for tk in tickers:
            rows.append({
                "Date": d, "ticker": tk,
                "ret_5": rng.normal(), "fwd_ret_5": rng.normal(0, 0.01),
            })
    base_panel = pd.DataFrame(rows)

    def pr(panel):
        return (panel["weight"] * panel["fwd_ret_5"]).groupby(panel["Date"]).sum()

    sens = parameter_sensitivity(
        base_panel, ["mr_ret_5"], pr, CostConfig(),
        base_long=0.8, base_short=0.2, delta=0.05,
    )
    longs = {p["long"] for p in sens["points"]}
    shorts = {p["short"] for p in sens["points"]}
    # long perturbed around 0.8, short perturbed around 0.2
    assert 0.75 in longs and 0.85 in longs
    assert 0.15 in shorts and 0.25 in shorts
    assert "net_sharpe_spread" in sens
