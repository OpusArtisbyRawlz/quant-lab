"""
BE-3 — Tick / volume / dollar bar sampling: deterministic unit tests.

These exercise the event-driven builders in ``src/data/bars/`` on **synthetic**
data only. They assert the algorithms are correct, pure, deterministic, and
conservative (OHLCV aggregation preserves first/max/min/last/sum), and — the
architectural point — that the event bars remain **disabled for real callers**:
``BarEngine.build`` refuses them unless ``allow_experimental=True``.

No network, no disk, fixed construction. Imports only from ``src.data.bars``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.bars import (
    BarEngine,
    SamplingSpec,
    BarResult,
    PRODUCTION_BAR_TYPES,
    IMPLEMENTED_BAR_TYPES,
)


# ---------------------------------------------------------------------------
# Deterministic synthetic OHLCV
# ---------------------------------------------------------------------------

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


def _handmade() -> pd.DataFrame:
    """Six rows with known values so aggregation is checkable by hand."""
    idx = pd.DatetimeIndex(pd.date_range("2021-01-04", periods=6, freq="B"), name="Date")
    return pd.DataFrame({
        "Open":   [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
        "High":   [10.5, 11.9, 12.4, 13.7, 14.2, 15.9],
        "Low":    [ 9.8, 10.7, 11.5, 12.6, 13.9, 14.4],
        "Close":  [11.0, 12.0, 13.0, 14.0, 15.0, 16.0],
        "Volume": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
    }, index=idx)


def _build(raw, spec):
    return BarEngine.build(raw, spec, allow_experimental=True)


# ===========================================================================
# 1. Production gate — event bars are NOT enabled for real callers
# ===========================================================================

@pytest.mark.parametrize("bar_type", ["tick", "volume", "dollar"])
def test_event_bars_blocked_without_experimental_flag(bar_type):
    raw = _make_data_dict()
    spec = SamplingSpec(type=bar_type, params={"threshold": 3})
    # Default build() (what the M7 executor calls) must refuse.
    with pytest.raises(NotImplementedError):
        BarEngine.build(raw, spec)
    # But the algorithm exists and runs when explicitly opted in.
    result = BarEngine.build(raw, spec, allow_experimental=True)
    assert isinstance(result, BarResult)


def test_event_bars_are_implemented_but_not_production():
    for bt in ("tick", "volume", "dollar"):
        assert bt in IMPLEMENTED_BAR_TYPES
        assert bt not in PRODUCTION_BAR_TYPES


# ===========================================================================
# 2. Tick bars — group every N rows
# ===========================================================================

def test_tick_bars_group_every_n_rows_handmade():
    raw = {"X": _handmade()}
    out = _build(raw, SamplingSpec(type="tick", params={"threshold": 3})).data["X"]
    assert len(out) == 2                      # 6 rows / 3
    # Bar 0 = rows 0..2, bar 1 = rows 3..5
    assert out["Open"].tolist()  == [10.0, 13.0]     # first of each group
    assert out["Close"].tolist() == [13.0, 16.0]     # last of each group
    assert out["High"].tolist()  == [12.4, 15.9]     # max of each group
    assert out["Low"].tolist()   == [9.8, 12.6]      # min of each group
    assert out["Volume"].tolist() == [300.0, 300.0]  # sum of each group


def test_tick_bars_partial_final_bar():
    raw = {"X": _handmade()}
    out = _build(raw, SamplingSpec(type="tick", params={"threshold": 4})).data["X"]
    assert len(out) == 2                      # rows 0..3, then partial 4..5
    assert out["Volume"].tolist() == [400.0, 200.0]


def test_tick_threshold_one_is_identity_length():
    raw = _make_data_dict()
    out = _build(raw, SamplingSpec(type="tick", params={"threshold": 1})).data
    for t in raw:
        assert len(out[t]) == len(raw[t])     # one bar per row


# ===========================================================================
# 3. Volume bars — accumulate Volume to a threshold
# ===========================================================================

def test_volume_bars_close_on_threshold_handmade():
    raw = {"X": _handmade()}                   # every Volume == 100
    out = _build(raw, SamplingSpec(type="volume", params={"threshold": 250})).data["X"]
    # acc: 100,200,300(>=250 close)->bar0 rows0..2 ; 100,200,300 close->bar1 rows3..5
    assert len(out) == 2
    assert out["Volume"].tolist() == [300.0, 300.0]
    assert out["Close"].tolist() == [13.0, 16.0]


def test_volume_bars_conserve_total_volume():
    raw = _make_data_dict()
    out = _build(raw, SamplingSpec(type="volume", params={"threshold": 2_000_000})).data
    for t in raw:
        assert out[t]["Volume"].sum() == pytest.approx(raw[t]["Volume"].sum())


# ===========================================================================
# 4. Dollar bars — accumulate Close*Volume to a threshold
# ===========================================================================

def test_dollar_bars_close_on_value_threshold_handmade():
    raw = {"X": _handmade()}
    # per-row dollar value = Close*Volume: 1100,1200,1300,1400,1500,1600
    out = _build(raw, SamplingSpec(type="dollar", params={"threshold": 2300})).data["X"]
    # acc 1100, 2300(>=2300 close)->bar0 rows0..1; 1300,2700 close->bar1 rows2..3;
    #     1500,3100 close->bar2 rows4..5
    assert len(out) == 3
    assert out["Volume"].tolist() == [200.0, 200.0, 200.0]
    assert out["Close"].tolist() == [12.0, 14.0, 16.0]


def test_dollar_bars_conserve_total_volume():
    raw = _make_data_dict()
    out = _build(raw, SamplingSpec(type="dollar", params={"threshold": 5.0e10})).data
    for t in raw:
        assert out[t]["Volume"].sum() == pytest.approx(raw[t]["Volume"].sum())


# ===========================================================================
# 5. Structural invariants shared by all event bars
# ===========================================================================

@pytest.mark.parametrize("bar_type,params", [
    ("tick",   {"threshold": 5}),
    ("volume", {"threshold": 1_500_000}),
    ("dollar", {"threshold": 3.0e10}),
])
def test_event_bars_preserve_ohlcv_invariants(bar_type, params):
    raw = _make_data_dict()
    out = _build(raw, SamplingSpec(type=bar_type, params=params)).data
    for t in raw:
        df = out[t]
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == "Date"
        assert df.index.is_monotonic_increasing
        assert not df.index.has_duplicates
        # High is the group max, Low the group min → High >= Low always.
        assert (df["High"] >= df["Low"]).all()
        assert (df["Volume"] > 0).all()


@pytest.mark.parametrize("bar_type,params", [
    ("tick",   {"threshold": 4}),
    ("volume", {"threshold": 1_200_000}),
    ("dollar", {"threshold": 2.5e10}),
])
def test_event_bars_are_deterministic(bar_type, params):
    raw = _make_data_dict()
    a = _build(raw, SamplingSpec(type=bar_type, params=params)).data
    b = _build(raw, SamplingSpec(type=bar_type, params=params)).data
    assert set(a) == set(b)
    for t in a:
        pd.testing.assert_frame_equal(a[t], b[t])


@pytest.mark.parametrize("bar_type", ["tick", "volume", "dollar"])
def test_event_bars_do_not_mutate_input(bar_type):
    raw = _make_data_dict()
    snapshot = {t: df.copy(deep=True) for t, df in raw.items()}
    _build(raw, SamplingSpec(type=bar_type, params={"threshold": 3}))
    for t in raw:
        pd.testing.assert_frame_equal(raw[t], snapshot[t])


# ===========================================================================
# 6. Parameter validation
# ===========================================================================

@pytest.mark.parametrize("bar_type", ["tick", "volume", "dollar"])
def test_event_bars_derive_default_threshold(bar_type):
    """With no explicit threshold, the engine derives a pooled default from data.

    This keeps the M7 executor bar-agnostic: it hands the engine only a bare
    bar-type string, and the engine sizes the threshold from the input itself.
    The result must still be a valid, non-empty set of bars.
    """
    raw = _make_data_dict()
    result = _build(raw, SamplingSpec(type=bar_type))       # no threshold → default
    assert isinstance(result, BarResult)
    assert set(result.data) == set(raw)
    for df in result.data.values():
        assert len(df) >= 1
    # Deterministic: same input → identical default-sized bars.
    again = _build(raw, SamplingSpec(type=bar_type))
    for t in result.data:
        pd.testing.assert_frame_equal(result.data[t], again.data[t])


@pytest.mark.parametrize("bar_type", ["tick", "volume", "dollar"])
def test_event_bars_reject_nonpositive_threshold(bar_type):
    raw = _make_data_dict()
    with pytest.raises(ValueError):
        _build(raw, SamplingSpec(type=bar_type, params={"threshold": 0}))
