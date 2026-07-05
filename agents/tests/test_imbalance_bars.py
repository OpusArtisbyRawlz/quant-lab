"""
BE-4 — Tick / volume / dollar imbalance bar sampling: deterministic unit tests.

Imbalance bars sign each row by the tick rule and close when the absolute signed
imbalance (count / volume / value) crosses a threshold. These tests exercise the
builders on **synthetic** data only, assert correctness against hand-computed
fixtures, and confirm the architectural gate: imbalance bars are implemented but
remain **disabled for real callers** unless ``allow_experimental=True``.

No network, no disk. Imports only from ``src.data.bars``.
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
    BAR_TYPES,
)
from src.data.bars.imbalance import tick_signs

IMBALANCE_TYPES = ["tick_imbalance", "volume_imbalance", "dollar_imbalance"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_data_dict(n_dates=60, n_tickers=3, seed=17) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-02-01", periods=n_dates, freq="B")
    out: dict[str, pd.DataFrame] = {}
    for i in range(n_tickers):
        prices = 40 * np.cumprod(1 + rng.normal(0.0, 0.015, n_dates))
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


def _imb_handmade() -> pd.DataFrame:
    """Close path with known sign flips; Volume flat at 100 for easy arithmetic.

    Close  : 10, 11, 10,  9, 12, 13
    signs  : +1, +1, -1, -1, +1, +1   (tick rule, b_0 = +1)
    """
    idx = pd.DatetimeIndex(pd.date_range("2021-02-01", periods=6, freq="B"), name="Date")
    return pd.DataFrame({
        "Open":   [10.0, 10.5, 10.5, 9.5, 9.5, 12.5],
        "High":   [10.9, 11.9, 11.0, 10.0, 12.9, 13.9],
        "Low":    [ 9.5, 10.0,  9.5, 8.5, 9.0, 12.0],
        "Close":  [10.0, 11.0, 10.0, 9.0, 12.0, 13.0],
        "Volume": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
    }, index=idx)


def _build(raw, spec):
    return BarEngine.build(raw, spec, allow_experimental=True)


# ===========================================================================
# 1. Tick rule
# ===========================================================================

def test_tick_signs_follow_tick_rule():
    close = np.array([10.0, 11.0, 10.0, 9.0, 12.0, 13.0])
    assert tick_signs(close).tolist() == [1, 1, -1, -1, 1, 1]


def test_tick_signs_carry_previous_on_no_change():
    close = np.array([10.0, 9.0, 9.0, 9.0, 10.0])
    # first +1; down -1; flat carries -1; flat carries -1; up +1
    assert tick_signs(close).tolist() == [1, -1, -1, -1, 1]


# ===========================================================================
# 2. Production gate — imbalance bars are NOT enabled for real callers
# ===========================================================================

@pytest.mark.parametrize("bar_type", IMBALANCE_TYPES)
def test_imbalance_blocked_without_experimental_flag(bar_type):
    raw = _make_data_dict()
    spec = SamplingSpec(type=bar_type, params={"threshold": 3})
    with pytest.raises(NotImplementedError):
        BarEngine.build(raw, spec)                      # default: executor path
    assert isinstance(BarEngine.build(raw, spec, allow_experimental=True), BarResult)


def test_imbalance_implemented_but_not_production():
    for bt in IMBALANCE_TYPES:
        assert bt in IMPLEMENTED_BAR_TYPES
        assert bt not in PRODUCTION_BAR_TYPES
    # BE-4 completes the vocabulary: everything recognised now has a builder.
    assert IMPLEMENTED_BAR_TYPES == frozenset(BAR_TYPES)


# ===========================================================================
# 3. Hand-checked boundaries
# ===========================================================================

def test_tick_imbalance_handmade():
    raw = {"X": _imb_handmade()}                        # signs +1,+1,-1,-1,+1,+1
    out = _build(raw, SamplingSpec(type="tick_imbalance", params={"threshold": 2})).data["X"]
    # acc: +1,+2(close)->bar0 r0..1 ; -1,-2(close)->bar1 r2..3 ; +1,+2(close)->bar2 r4..5
    assert len(out) == 3
    assert out["Open"].tolist()  == [10.0, 10.5, 9.5]
    assert out["Close"].tolist() == [11.0, 9.0, 13.0]
    assert out["Volume"].tolist() == [200.0, 200.0, 200.0]


def test_volume_imbalance_handmade():
    raw = {"X": _imb_handmade()}                        # signed volume ±100
    out = _build(raw, SamplingSpec(type="volume_imbalance", params={"threshold": 200})).data["X"]
    # acc: +100,+200(close); -100,-200(close); +100,+200(close)
    assert len(out) == 3
    assert out["Volume"].tolist() == [200.0, 200.0, 200.0]
    assert out["Close"].tolist() == [11.0, 9.0, 13.0]


def test_dollar_imbalance_handmade():
    raw = {"X": _imb_handmade()}
    # signed value = sign*Close*Volume:
    #   +1000, +1100, -1000, -900, +1200, +1300
    out = _build(raw, SamplingSpec(type="dollar_imbalance", params={"threshold": 1500})).data["X"]
    # acc: 1000,2100(>=1500 close) r0..1; -1000,-1900(close) r2..3; 1200,2500(close) r4..5
    assert len(out) == 3
    assert out["Volume"].tolist() == [200.0, 200.0, 200.0]
    assert out["Close"].tolist() == [11.0, 9.0, 13.0]


def test_imbalance_partial_final_bar():
    raw = {"X": _imb_handmade()}
    # Large threshold never crossed → a single trailing partial bar over all rows.
    out = _build(raw, SamplingSpec(type="tick_imbalance", params={"threshold": 999})).data["X"]
    assert len(out) == 1
    assert out["Volume"].tolist() == [600.0]
    assert out["Open"].iloc[0] == 10.0
    assert out["Close"].iloc[0] == 13.0


# ===========================================================================
# 4. Structural invariants + purity + determinism
# ===========================================================================

@pytest.mark.parametrize("bar_type,params", [
    ("tick_imbalance",   {"threshold": 3}),
    ("volume_imbalance", {"threshold": 1_500_000}),
    ("dollar_imbalance", {"threshold": 3.0e10}),
])
def test_imbalance_preserve_ohlcv_invariants(bar_type, params):
    raw = _make_data_dict()
    out = _build(raw, SamplingSpec(type=bar_type, params=params)).data
    for t in raw:
        df = out[t]
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == "Date"
        assert df.index.is_monotonic_increasing
        assert not df.index.has_duplicates
        assert (df["High"] >= df["Low"]).all()
        assert (df["Volume"] > 0).all()
        # Volume is conserved by the aggregation.
        assert df["Volume"].sum() == pytest.approx(raw[t]["Volume"].sum())


@pytest.mark.parametrize("bar_type", IMBALANCE_TYPES)
def test_imbalance_are_deterministic(bar_type):
    raw = _make_data_dict()
    spec = SamplingSpec(type=bar_type, params={"threshold": 2.0e9})
    a = _build(raw, spec).data
    b = _build(raw, spec).data
    for t in a:
        pd.testing.assert_frame_equal(a[t], b[t])


@pytest.mark.parametrize("bar_type", IMBALANCE_TYPES)
def test_imbalance_do_not_mutate_input(bar_type):
    raw = _make_data_dict()
    snap = {t: df.copy(deep=True) for t, df in raw.items()}
    _build(raw, SamplingSpec(type=bar_type, params={"threshold": 5}))
    for t in raw:
        pd.testing.assert_frame_equal(raw[t], snap[t])


# ===========================================================================
# 5. Parameter validation
# ===========================================================================

@pytest.mark.parametrize("bar_type", IMBALANCE_TYPES)
def test_imbalance_derive_default_threshold(bar_type):
    """No explicit threshold → the engine derives a pooled default from data.

    Imbalance variants reuse the scale of their non-imbalance counterpart, so a
    bare bar-type string still yields valid, deterministic bars.
    """
    raw = _make_data_dict()
    result = _build(raw, SamplingSpec(type=bar_type))
    assert set(result.data) == set(raw)
    for df in result.data.values():
        assert len(df) >= 1
    again = _build(raw, SamplingSpec(type=bar_type))
    for t in result.data:
        pd.testing.assert_frame_equal(result.data[t], again.data[t])


@pytest.mark.parametrize("bar_type", IMBALANCE_TYPES)
def test_imbalance_reject_nonpositive_threshold(bar_type):
    raw = _make_data_dict()
    with pytest.raises(ValueError):
        _build(raw, SamplingSpec(type=bar_type, params={"threshold": -1}))
