"""
Prerequisite #2 — realised periods-per-year for event-bar metrics.

Daily time bars annualise at 252; event bars (tick / volume / dollar /
imbalance) close at irregular, data-driven timestamps, so annualising them with
252 misstates their risk-adjusted metrics. ``realized_periods_per_year`` measures
the cadence from the bars themselves, and the event builders return it on
``BarResult.periods_per_year``. These tests prove:

* **identity** — time bars still report exactly 252 (byte-identical production
  path); the runner's time-bar metrics are unchanged;
* **correctness** — pooled bars-per-year on a hand-built irregular example;
* event builders report a *realised* cadence (< 252 when bars are sparser than
  daily), while an explicit spec override always wins;
* purity, determinism, and sane degenerate-input behaviour.

Imports only from ``src.data.bars`` — no agent dependency for the engine tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.bars import (
    BarEngine,
    SamplingSpec,
    realized_periods_per_year,
    event_periods_per_year,
)
from src.data.bars.periods import DAYS_PER_YEAR
from src.data.bars.base import DEFAULT_PERIODS_PER_YEAR


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_data_dict(n_dates=260, n_tickers=6, seed=11) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    out: dict[str, pd.DataFrame] = {}
    for i in range(n_tickers):
        prices = 100 * np.cumprod(1 + rng.normal(0.0004, 0.011, n_dates))
        df = pd.DataFrame({
            "Open":   prices * rng.uniform(0.99, 1.00, n_dates),
            "High":   prices * rng.uniform(1.00, 1.01, n_dates),
            "Low":    prices * rng.uniform(0.98, 1.00, n_dates),
            "Close":  prices,
            "Volume": rng.integers(500_000, 2_000_000, n_dates).astype(float),
        }, index=dates)
        df.index.name = "Date"
        out[f"T{i:02d}"] = df
    return out


def _frame(dates) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    n = len(dates)
    return pd.DataFrame({
        "Open": [1.0] * n, "High": [1.0] * n, "Low": [1.0] * n,
        "Close": [1.0] * n, "Volume": [1.0] * n,
    }, index=idx)


# ===========================================================================
# 1. realized_periods_per_year — correctness on hand-built grids
# ===========================================================================

def test_realized_ppy_pooled_bars_per_year():
    # One ticker, 5 bars exactly 365.25 days apart end-to-end → 4 intervals over
    # 1 year → 4 bars/year.
    span = pd.Timedelta(days=DAYS_PER_YEAR)
    start = pd.Timestamp("2020-01-01")
    dates = [start + i * (span / 4) for i in range(5)]
    ppy = realized_periods_per_year({"A": _frame(dates)})
    assert ppy == pytest.approx(4.0)


def test_realized_ppy_pools_across_tickers():
    # A: 3 bars over 365.25d → 2 intervals / 1y. B: 2 bars over 365.25d → 1/1y.
    # Pooled = (2 + 1) intervals / (1 + 1) years = 1.5 bars/year.
    span = pd.Timedelta(days=DAYS_PER_YEAR)
    a = _frame([pd.Timestamp("2020-01-01") + i * (span / 2) for i in range(3)])
    b = _frame([pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-01") + span])
    assert realized_periods_per_year({"A": a, "B": b}) == pytest.approx(1.5)


def test_realized_ppy_daily_business_days_near_252():
    # ~252 business days over a year annualises close to (but not exactly) 252.
    dates = pd.date_range("2020-01-02", periods=252, freq="B")
    ppy = realized_periods_per_year({"A": _frame(dates)})
    assert 240 < ppy < 265
    assert ppy != DEFAULT_PERIODS_PER_YEAR  # measured, not the constant


def test_realized_ppy_degenerate_returns_default():
    assert realized_periods_per_year({}) == DEFAULT_PERIODS_PER_YEAR
    # single bar → no interval to measure
    assert realized_periods_per_year(
        {"A": _frame(["2020-01-01"])}
    ) == DEFAULT_PERIODS_PER_YEAR
    # custom default honoured
    assert realized_periods_per_year({}, default=99.0) == 99.0


def test_realized_ppy_is_pure_and_deterministic():
    bars = {"A": _frame(pd.date_range("2020-01-02", periods=40, freq="B"))}
    snap = bars["A"].copy(deep=True)
    a = realized_periods_per_year(bars)
    b = realized_periods_per_year(bars)
    assert a == b
    pd.testing.assert_frame_equal(bars["A"], snap)  # no mutation


# ===========================================================================
# 2. event_periods_per_year resolver — override wins, else measured
# ===========================================================================

def test_event_ppy_uses_override_when_present():
    bars = {"A": _frame(pd.date_range("2020-01-02", periods=10, freq="B"))}
    spec = SamplingSpec("volume", params={"threshold": 1.0}, periods_per_year=52.0)
    assert event_periods_per_year(spec, bars) == 52.0


def test_event_ppy_measures_when_no_override():
    bars = {"A": _frame(pd.date_range("2020-01-02", periods=252, freq="B"))}
    spec = SamplingSpec("volume", params={"threshold": 1.0})
    assert event_periods_per_year(spec, bars) == realized_periods_per_year(bars)


# ===========================================================================
# 3. Identity — the time path keeps 252 exactly (byte-identical)
# ===========================================================================

def test_time_bars_report_exactly_252():
    raw = _make_data_dict()
    result = BarEngine.build(raw, SamplingSpec("time"))
    assert result.periods_per_year == DEFAULT_PERIODS_PER_YEAR == 252.0


def test_time_bars_honour_explicit_override():
    raw = _make_data_dict()
    result = BarEngine.build(raw, SamplingSpec("time", periods_per_year=12.0))
    assert result.periods_per_year == 12.0


# ===========================================================================
# 4. Event bars report a realised cadence via BarResult
# ===========================================================================

@pytest.mark.parametrize("bar_type", ["tick", "volume", "dollar"])
def test_event_bars_report_realized_cadence_below_daily(bar_type):
    raw = _make_data_dict()
    if bar_type == "tick":
        params = {"threshold": 5}          # 5 daily rows per bar
    elif bar_type == "volume":
        params = {"threshold": 5_000_000}
    else:
        params = {"threshold": 500_000_000}
    result = BarEngine.build(
        raw, SamplingSpec(bar_type, params=params), allow_experimental=True
    )
    ppy = result.periods_per_year
    # Bars aggregate several daily rows, so the cadence is well below 252...
    assert 0 < ppy < DEFAULT_PERIODS_PER_YEAR
    # ...and matches an independent measurement of the produced bars.
    assert ppy == pytest.approx(realized_periods_per_year(result.data))


def test_imbalance_bars_report_realized_cadence():
    raw = _make_data_dict()
    result = BarEngine.build(
        raw, SamplingSpec("volume_imbalance", params={"threshold": 8_000_000}),
        allow_experimental=True,
    )
    assert 0 < result.periods_per_year < DEFAULT_PERIODS_PER_YEAR
    assert result.periods_per_year == pytest.approx(
        realized_periods_per_year(result.data)
    )


def test_event_bar_ppy_override_flows_through_build():
    raw = _make_data_dict()
    result = BarEngine.build(
        raw, SamplingSpec("volume", params={"threshold": 5_000_000},
                          periods_per_year=26.0),
        allow_experimental=True,
    )
    assert result.periods_per_year == 26.0
