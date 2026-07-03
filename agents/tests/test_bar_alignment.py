"""
Prerequisite #1 — cross-sectional alignment for irregular event bars.

``align_cross_section`` maps per-ticker, irregularly-timestamped event bars onto
a shared union grid via as-of (forward-fill) reindexing, so the cross-sectional
alpha pipeline can ``groupby("Date")`` and see a full peer group at each grid
point. These tests prove:

* **identity** — already-aligned (daily time) bars pass through unchanged, and
  routing them through the real pipeline is byte-identical to today;
* **correctness** — union grid + forward-fill on a hand-built irregular example;
* purity, determinism, no-lookahead, and method validation.

Imports only from ``src.data.bars`` / ``src.pipelines`` — no agent dependency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.bars import (
    BarEngine,
    SamplingSpec,
    align_cross_section,
    ALIGNMENT_METHODS,
)
from src.pipelines.cross_sectional import run_market_alpha_pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_data_dict(n_dates=80, n_tickers=6, seed=7) -> dict[str, pd.DataFrame]:
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


def _frame(dates, closes) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    n = len(dates)
    return pd.DataFrame({
        "Open":   [float(c) for c in closes],
        "High":   [float(c) + 1 for c in closes],
        "Low":    [float(c) - 1 for c in closes],
        "Close":  [float(c) for c in closes],
        "Volume": [100.0] * n,
    }, index=idx)


def _irregular_two_tickers() -> dict[str, pd.DataFrame]:
    # A closes on 04/06/08; B closes on 05/06/07 — different, irregular grids.
    a = _frame(["2021-01-04", "2021-01-06", "2021-01-08"], [10, 12, 14])
    b = _frame(["2021-01-05", "2021-01-06", "2021-01-07"], [20, 21, 22])
    return {"A": a, "B": b}


# ===========================================================================
# 1. Identity — alignment must not disturb the current (time) production path
# ===========================================================================

def test_alignment_is_identity_for_daily_time_bars():
    raw = _make_data_dict()
    bars = BarEngine.build(raw, SamplingSpec("time")).data   # shared daily grid
    aligned = align_cross_section(bars)
    assert set(aligned) == set(bars)
    for t in bars:
        pd.testing.assert_frame_equal(aligned[t], bars[t])


def test_pipeline_byte_identical_through_alignment_for_time_bars():
    raw = _make_data_dict()
    before = run_market_alpha_pipeline(raw)
    aligned = align_cross_section(BarEngine.build(raw, SamplingSpec("time")).data)
    after = run_market_alpha_pipeline(aligned)
    pd.testing.assert_frame_equal(before, after)


# ===========================================================================
# 2. Correctness on a hand-built irregular example
# ===========================================================================

def test_union_grid_is_sorted_union_of_all_close_times():
    aligned = align_cross_section(_irregular_two_tickers())
    expected = pd.DatetimeIndex(
        pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06",
                        "2021-01-07", "2021-01-08"]),
        name="Date",
    )
    for t in aligned:
        pd.testing.assert_index_equal(aligned[t].index, expected)


def test_asof_forward_fill_values():
    aligned = align_cross_section(_irregular_two_tickers())
    # A closes 04=10, 06=12, 08=14 → ffill across the 5-point grid
    assert aligned["A"]["Close"].tolist() == [10.0, 10.0, 12.0, 12.0, 14.0]
    # B first bar is 05 → 04 is NaN (not in the cross-section yet), then ffill
    b_close = aligned["B"]["Close"].tolist()
    assert np.isnan(b_close[0])
    assert b_close[1:] == [20.0, 21.0, 22.0, 22.0]


def test_alignment_enables_full_cross_section_groups():
    aligned = align_cross_section(_irregular_two_tickers())
    # Stack like the pipeline does and count tickers present per grid date.
    frames = []
    for t, df in aligned.items():
        d = df.copy()
        d["Date"] = d.index
        d["ticker"] = t
        frames.append(d.dropna())
    panel = pd.concat(frames).reset_index(drop=True)
    counts = panel.groupby("Date")["ticker"].nunique()
    # From 01-05 onward both tickers are present → cross-section of size 2.
    assert (counts.loc["2021-01-05":] == 2).all()


# ===========================================================================
# 3. Purity / determinism / no-lookahead / validation
# ===========================================================================

def test_alignment_does_not_mutate_input():
    bars = _irregular_two_tickers()
    snap = {t: df.copy(deep=True) for t, df in bars.items()}
    align_cross_section(bars)
    for t in bars:
        pd.testing.assert_frame_equal(bars[t], snap[t])


def test_alignment_is_deterministic():
    bars = _irregular_two_tickers()
    a = align_cross_section(bars)
    b = align_cross_section(bars)
    for t in a:
        pd.testing.assert_frame_equal(a[t], b[t])


def test_alignment_has_no_lookahead():
    # Every aligned value must equal a bar that closed at or before that grid time.
    bars = _irregular_two_tickers()
    aligned = align_cross_section(bars)
    for t, adf in aligned.items():
        src = bars[t]
        for ts, val in adf["Close"].items():
            prior = src.loc[src.index <= ts, "Close"]
            if prior.empty:
                assert np.isnan(val)
            else:
                assert val == prior.iloc[-1]


def test_alignment_rejects_unknown_method():
    with pytest.raises(ValueError):
        align_cross_section(_irregular_two_tickers(), method="interpolate")
    assert "asof" in ALIGNMENT_METHODS


def test_alignment_empty_input_returns_empty():
    assert align_cross_section({}) == {}


# ===========================================================================
# 4. Works on real engine-produced event bars (experimental path)
# ===========================================================================

def test_alignment_on_volume_bars_shares_one_grid():
    raw = _make_data_dict()
    bars = BarEngine.build(
        raw, SamplingSpec("volume", params={"threshold": 3_000_000}),
        allow_experimental=True,
    ).data
    # Per-ticker volume bars close on different dates...
    distinct = {t: tuple(df.index) for t, df in bars.items()}
    assert len(set(distinct.values())) > 1
    # ...after alignment every ticker shares the identical grid.
    aligned = align_cross_section(bars)
    grids = [tuple(df.index) for df in aligned.values()]
    assert len(set(grids)) == 1
