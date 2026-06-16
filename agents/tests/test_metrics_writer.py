"""Tests for experiment_runner/metrics_writer.py."""

import json
import math
import numpy as np
import pandas as pd
import pytest

from agents.experiment_runner.metrics_writer import (
    compute_metrics,
    write_metrics_json,
    write_strategy_csv,
    _nan_to_none,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_returns():
    """Constant positive return — deterministic metrics."""
    return pd.Series([0.001] * 252)


@pytest.fixture
def random_returns(seed=42):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0005, 0.01, 252))


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

def test_compute_metrics_returns_expected_keys(flat_returns):
    m = compute_metrics(flat_returns)
    assert set(m) == {"sharpe", "mdd", "cagr", "vol", "calmar"}


def test_sharpe_positive_for_positive_returns(flat_returns):
    m = compute_metrics(flat_returns)
    assert m["sharpe"] > 0


def test_mdd_is_negative_or_zero(random_returns):
    m = compute_metrics(random_returns)
    assert m["mdd"] <= 0


def test_cagr_positive_for_flat_positive_returns(flat_returns):
    m = compute_metrics(flat_returns)
    assert m["cagr"] > 0


def test_calmar_computed_from_cagr_and_mdd(random_returns):
    m = compute_metrics(random_returns)
    if m["cagr"] is not None and m["mdd"] is not None and m["mdd"] != 0:
        expected = m["cagr"] / abs(m["mdd"])
        assert abs(m["calmar"] - expected) < 1e-3


def test_calmar_none_when_mdd_zero():
    # Monotonically increasing — mdd = 0
    returns = pd.Series([0.01] * 10)
    m = compute_metrics(returns)
    assert m["calmar"] is None


def test_empty_series_returns_none_metrics():
    m = compute_metrics(pd.Series([], dtype=float))
    assert all(v is None for v in m.values())


def test_all_nan_series_returns_none_metrics():
    m = compute_metrics(pd.Series([float("nan")] * 10))
    assert all(v is None for v in m.values())


def test_metrics_are_rounded(random_returns):
    m = compute_metrics(random_returns)
    for key, val in m.items():
        if val is not None:
            # Should have at most 6 decimal places
            assert round(val, 6) == val, f"{key} not rounded: {val}"


# ---------------------------------------------------------------------------
# write_metrics_json
# ---------------------------------------------------------------------------

def test_write_metrics_json_creates_file(tmp_path, random_returns):
    m = compute_metrics(random_returns)
    write_metrics_json(m, tmp_path)
    assert (tmp_path / "metrics.json").exists()


def test_write_metrics_json_round_trips(tmp_path, random_returns):
    m = compute_metrics(random_returns)
    write_metrics_json(m, tmp_path)
    loaded = json.loads((tmp_path / "metrics.json").read_text())
    for key in ("sharpe", "mdd", "cagr", "vol"):
        if m[key] is not None:
            assert abs(loaded[key] - m[key]) < 1e-6


def test_write_metrics_json_no_nan_in_output(tmp_path, random_returns):
    m = compute_metrics(random_returns)
    write_metrics_json(m, tmp_path)
    text = (tmp_path / "metrics.json").read_text()
    assert "NaN" not in text
    assert "Infinity" not in text


# ---------------------------------------------------------------------------
# write_strategy_csv
# ---------------------------------------------------------------------------

def test_write_strategy_csv_creates_file(tmp_path):
    variant = {"Strategy": "S1", "Sharpe": 1.2, "MDD": -0.3,
                "CAGR": 0.15, "Vol": 0.12, "Calmar": 0.5}
    write_strategy_csv([variant], tmp_path)
    assert (tmp_path / "strategy_comparison.csv").exists()


def test_write_strategy_csv_correct_columns(tmp_path):
    variant = {"Strategy": "S1", "Sharpe": 1.2, "MDD": -0.3,
                "CAGR": 0.15, "Vol": 0.12, "Calmar": 0.5}
    write_strategy_csv([variant], tmp_path)
    import csv
    with open(tmp_path / "strategy_comparison.csv") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["Strategy"] == "S1"
    assert float(rows[0]["Sharpe"]) == pytest.approx(1.2)


def test_write_strategy_csv_extra_columns_appended(tmp_path):
    variant = {"Strategy": "S1", "Sharpe": 1.2, "MDD": -0.3,
                "CAGR": 0.15, "Vol": 0.12, "Calmar": 0.5,
                "Signal Combo": "mr_ret_10 + low_vol_20"}
    write_strategy_csv([variant], tmp_path)
    import csv
    with open(tmp_path / "strategy_comparison.csv") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert "Signal Combo" in rows[0]
    assert rows[0]["Signal Combo"] == "mr_ret_10 + low_vol_20"


def test_write_strategy_csv_multiple_rows(tmp_path):
    variants = [
        {"Strategy": f"S{i}", "Sharpe": i * 0.5, "MDD": -0.2,
         "CAGR": 0.1, "Vol": 0.1, "Calmar": 0.5}
        for i in range(1, 4)
    ]
    write_strategy_csv(variants, tmp_path)
    import csv
    with open(tmp_path / "strategy_comparison.csv") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3


def test_write_strategy_csv_empty_list_no_file(tmp_path):
    write_strategy_csv([], tmp_path)
    assert not (tmp_path / "strategy_comparison.csv").exists()


# ---------------------------------------------------------------------------
# _nan_to_none helper
# ---------------------------------------------------------------------------

def test_nan_to_none_converts_nan():
    assert _nan_to_none(float("nan")) is None


def test_nan_to_none_converts_inf():
    assert _nan_to_none(float("inf")) is None
    assert _nan_to_none(float("-inf")) is None


def test_nan_to_none_passes_regular_float():
    assert _nan_to_none(1.23456) == pytest.approx(1.23456)


def test_nan_to_none_rounds():
    val = _nan_to_none(1.123456789)
    assert val == pytest.approx(1.123457, abs=1e-6)
