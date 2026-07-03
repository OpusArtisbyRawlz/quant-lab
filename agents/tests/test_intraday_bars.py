"""
Prerequisite #3 — intraday data makes event bars *genuine*.

The tick / volume / dollar / imbalance builders accumulate a threshold across
input rows. On daily OHLCV an event bar can never close within a day — the
sampling is only as fine as the input. Feed the SAME builders genuine intraday
observations and bars close *inside* a session, exactly as event bars are meant
to. These tests prove that end-to-end, and that the three prerequisites compose:

* **#3 intraday ingestion** — ``load_intraday`` frames flow straight into
  ``BarEngine.build``;
* **#1 alignment** — irregular intraday event bars align onto one grid;
* **#2 realised cadence** — the intraday cadence is far higher than the daily
  252, measured from the bars themselves.

The daily/time production path stays identity (byte-identical).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.bars import (
    BarEngine,
    SamplingSpec,
    align_cross_section,
    realized_periods_per_year,
)
from src.data.bars.base import DEFAULT_PERIODS_PER_YEAR
from agents.experiment_runner.intraday_loader import load_intraday


# ---------------------------------------------------------------------------
# Synthetic intraday data
# ---------------------------------------------------------------------------

def _intraday_dict(n_days=5, bars_per_day=13, n_tickers=4, seed=3):
    """Per-ticker frames with a genuine sub-daily timestamp index."""
    rng = np.random.default_rng(seed)
    stamps = []
    for d in range(n_days):
        day = pd.Timestamp("2021-06-01") + pd.Timedelta(days=d)
        stamps.extend(
            day + pd.Timedelta(minutes=30) * (13 + i)  # 09:30, 10:00, ...
            for i in range(bars_per_day)
        )
    idx = pd.DatetimeIndex(stamps, name="Timestamp")
    n = len(idx)
    out = {}
    for k in range(n_tickers):
        prices = 100 * np.cumprod(1 + rng.normal(0.0, 0.002, n))
        out[f"T{k}"] = pd.DataFrame({
            "Open": prices, "High": prices * 1.001, "Low": prices * 0.999,
            "Close": prices,
            "Volume": rng.integers(800, 1200, n).astype(float),
        }, index=idx)
    return out


def _bars_closing_within_a_day(df: pd.DataFrame) -> int:
    """How many calendar dates carry more than one bar-close timestamp."""
    per_day = pd.Series(df.index).dt.normalize().value_counts()
    return int((per_day > 1).sum())


# ===========================================================================
# 1. Intraday observations → event bars that close within a day
# ===========================================================================

def test_volume_bars_close_within_a_day_on_intraday():
    data = _intraday_dict()
    result = BarEngine.build(
        data, SamplingSpec("volume", params={"threshold": 3000}),
        allow_experimental=True,
    )
    # At least one ticker has multiple volume bars closing on the same calendar
    # date — impossible with one-observation-per-day daily data.
    assert any(_bars_closing_within_a_day(df) > 0 for df in result.data.values())


def test_daily_data_cannot_close_within_a_day():
    # Contrast: one row per day → every bar closes on a distinct date.
    dates = pd.date_range("2021-06-01", periods=30, freq="B")
    daily = {"A": pd.DataFrame({
        "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1000.0,
    }, index=pd.DatetimeIndex(dates, name="Date"))}
    result = BarEngine.build(
        daily, SamplingSpec("volume", params={"threshold": 3000}),
        allow_experimental=True,
    )
    assert _bars_closing_within_a_day(result.data["A"]) == 0


# ===========================================================================
# 2. Realised cadence reflects the intraday clock (#2 composes)
# ===========================================================================

def test_intraday_event_cadence_far_exceeds_daily():
    data = _intraday_dict()
    result = BarEngine.build(
        data, SamplingSpec("volume", params={"threshold": 3000}),
        allow_experimental=True,
    )
    # Bars several times a day → thousands of periods per year, not ~252.
    assert result.periods_per_year > 1000 * DEFAULT_PERIODS_PER_YEAR / 252  # > 1000
    assert result.periods_per_year == pytest.approx(
        realized_periods_per_year(result.data)
    )


# ===========================================================================
# 3. Alignment composes on intraday event bars (#1 composes)
# ===========================================================================

def test_intraday_event_bars_align_to_one_grid():
    data = _intraday_dict()
    bars = BarEngine.build(
        data, SamplingSpec("dollar", params={"threshold": 350_000}),
        allow_experimental=True,
    ).data
    # Per-ticker intraday bars close at different timestamps...
    assert len({tuple(df.index) for df in bars.values()}) > 1
    # ...alignment puts them on one shared intraday grid.
    aligned = align_cross_section(bars)
    assert len({tuple(df.index) for df in aligned.values()}) == 1


# ===========================================================================
# 4. Time bars on intraday data are identity (production path unaffected)
# ===========================================================================

def test_time_bars_identity_on_intraday_input():
    data = _intraday_dict()
    result = BarEngine.build(data, SamplingSpec("time"))
    assert result.periods_per_year == DEFAULT_PERIODS_PER_YEAR  # still 252
    for t, df in data.items():
        pd.testing.assert_frame_equal(result.data[t], df)


# ===========================================================================
# 5. End-to-end: loader → engine (ingestion feeds sampling directly)
# ===========================================================================

def test_loader_output_feeds_engine(tmp_path):
    d = tmp_path / "intraday"
    d.mkdir()
    ts = pd.date_range("2021-06-01 09:30", periods=40, freq="15min")
    for stem in ("aaa", "bbb"):
        pd.DataFrame({
            "Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "Open": 50.0, "High": 50.1, "Low": 49.9, "Close": 50.0,
            "Volume": 1000.0,
        }).to_csv(d / f"{stem}.csv", index=False)

    bundle = load_intraday(d)
    assert not bundle.warnings
    result = BarEngine.build(
        bundle.data_dict, SamplingSpec("tick", params={"threshold": 4}),
        allow_experimental=True,
    )
    # 40 rows / 4 per bar = 10 bars per ticker, some sharing a calendar date.
    for df in result.data.values():
        assert len(df) == 10
        assert _bars_closing_within_a_day(df) > 0
