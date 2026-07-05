"""
Data-derived default thresholds for event bars: deterministic unit tests.

When a caller supplies no ``params['threshold']`` the engine derives one from the
data itself so the M7 executor can stay bar-agnostic (it hands the engine only a
bare bar-type string). These tests pin the pooled sizing policy, its purity, and
the "explicit value always wins" contract. Synthetic data only; no I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.bars import (
    default_threshold,
    resolve_threshold,
    TARGET_BARS_PER_TICKER,
)


def _make_data_dict(n_dates=60, n_tickers=3, seed=11) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n_dates, freq="B")
    out: dict[str, pd.DataFrame] = {}
    for i in range(n_tickers):
        prices = 50 * np.cumprod(1 + rng.normal(0.0003, 0.012, n_dates))
        df = pd.DataFrame({
            "Open":   prices * rng.uniform(0.99, 1.00, n_dates),
            "High":   prices * rng.uniform(1.00, 1.02, n_dates),
            "Low":    prices * rng.uniform(0.98, 1.00, n_dates),
            "Close":  prices,
            "Volume": rng.integers(100_000, 1_000_000, n_dates).astype(float),
        }, index=dates)
        df.index.name = "Date"
        out[f"T{i:02d}"] = df
    return out


# ---------------------------------------------------------------------------
# Pooled sizing policy
# ---------------------------------------------------------------------------

def test_tick_default_is_rows_per_bar():
    raw = _make_data_dict(n_dates=60, n_tickers=3)
    denom = 3 * TARGET_BARS_PER_TICKER
    total_rows = sum(len(df) for df in raw.values())
    expected = float(max(1, round(total_rows / denom)))
    assert default_threshold("tick", raw) == expected


def test_volume_default_is_pooled_volume():
    raw = _make_data_dict()
    denom = len(raw) * TARGET_BARS_PER_TICKER
    total = sum(float(df["Volume"].sum()) for df in raw.values())
    assert default_threshold("volume", raw) == pytest.approx(total / denom)


def test_dollar_default_is_pooled_value():
    raw = _make_data_dict()
    denom = len(raw) * TARGET_BARS_PER_TICKER
    total = sum(float((df["Close"] * df["Volume"]).sum()) for df in raw.values())
    assert default_threshold("dollar", raw) == pytest.approx(total / denom)


@pytest.mark.parametrize("base,imb", [
    ("volume", "volume_imbalance"),
    ("dollar", "dollar_imbalance"),
    ("tick", "tick_imbalance"),
])
def test_imbalance_reuses_base_scale(base, imb):
    raw = _make_data_dict()
    assert default_threshold(imb, raw) == default_threshold(base, raw)


# ---------------------------------------------------------------------------
# Purity, determinism, edge cases
# ---------------------------------------------------------------------------

def test_default_is_positive_and_deterministic():
    raw = _make_data_dict()
    for bt in ("tick", "volume", "dollar",
               "tick_imbalance", "volume_imbalance", "dollar_imbalance"):
        a = default_threshold(bt, raw)
        b = default_threshold(bt, raw)
        assert a > 0 and a == b


def test_empty_data_raises():
    with pytest.raises(ValueError):
        default_threshold("volume", {})


def test_time_has_no_accumulator_scale():
    raw = _make_data_dict()
    with pytest.raises(ValueError):
        default_threshold("time", raw)


def test_nonpositive_total_raises():
    raw = _make_data_dict(n_dates=5, n_tickers=1)
    raw["T00"]["Volume"] = 0.0
    with pytest.raises(ValueError):
        default_threshold("volume", raw)


# ---------------------------------------------------------------------------
# resolve_threshold: explicit value always wins
# ---------------------------------------------------------------------------

def test_explicit_threshold_wins():
    raw = _make_data_dict()
    assert resolve_threshold("volume", 12345.0, raw) == 12345.0


def test_resolve_falls_back_to_default():
    raw = _make_data_dict()
    assert resolve_threshold("volume", None, raw) == default_threshold("volume", raw)


def test_target_bars_scales_threshold_inversely():
    raw = _make_data_dict()
    small_target = default_threshold("volume", raw, target_bars_per_ticker=10)
    large_target = default_threshold("volume", raw, target_bars_per_ticker=100)
    # More target bars → smaller threshold per bar.
    assert large_target < small_target
