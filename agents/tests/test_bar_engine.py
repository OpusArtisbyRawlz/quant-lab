"""
BE-1 — Bar Engine regression + identity-equivalence tests.

The Bar Engine is a `src`-layer infrastructure module (`src/data/bars/`) with no
dependency on the agent stack. These tests import only from `src` — they live
here purely so the project's single CI entry point (`pytest agents/tests/`)
discovers and runs them. A later PR may relocate them under a dedicated `tests/`
root with its own CI step.

The headline test is `test_time_bars_reproduce_pipeline_exactly`: routing data
through the engine in identity (time) mode must leave the existing
cross-sectional alpha pipeline byte-identical — the contract that lets BE-2 wire
the engine into M7 with zero behavioural change.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.bars import (
    BarEngine,
    build,
    SamplingSpec,
    BarResult,
    validate_bars,
    BarValidationError,
    BAR_TYPES,
    IMPLEMENTED_BAR_TYPES,
    DEFAULT_PERIODS_PER_YEAR,
)
from src.pipelines.cross_sectional import run_market_alpha_pipeline


# ---------------------------------------------------------------------------
# Deterministic synthetic OHLCV (no network, no disk, fixed seed)
# ---------------------------------------------------------------------------

def _make_data_dict(n_dates=80, n_tickers=6, seed=7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    out: dict[str, pd.DataFrame] = {}
    for i in range(n_tickers):
        prices = 100 * np.cumprod(1 + rng.normal(0.0004, 0.011, n_dates))
        df = pd.DataFrame({
            "Open": prices * rng.uniform(0.99, 1.00, n_dates),
            "High": prices * rng.uniform(1.00, 1.01, n_dates),
            "Low": prices * rng.uniform(0.98, 1.00, n_dates),
            "Close": prices,
            "Volume": rng.integers(500_000, 2_000_000, n_dates).astype(float),
        }, index=dates)
        df.index.name = "Date"
        out[f"T{i:02d}"] = df
    return out


# ===========================================================================
# 1. Identity equivalence — THE BE-1 acceptance test
# ===========================================================================

def test_time_bars_reproduce_pipeline_exactly():
    raw = _make_data_dict()

    # Baseline: today's pipeline straight on the raw data.
    panel_before = run_market_alpha_pipeline(raw)

    # Through the engine in identity (time) mode, then the same pipeline.
    result = BarEngine.build(raw, SamplingSpec(type="time"))
    panel_after = run_market_alpha_pipeline(result.data)

    pd.testing.assert_frame_equal(panel_before, panel_after)


def test_identity_data_equals_input_framewise():
    raw = _make_data_dict()
    out = BarEngine.build(raw, "time").data
    assert set(out) == set(raw)
    for t in raw:
        pd.testing.assert_frame_equal(out[t], raw[t])


# ===========================================================================
# 2. Purity — no mutation of the caller's data
# ===========================================================================

def test_build_does_not_mutate_input():
    raw = _make_data_dict()
    snapshot = {t: df.copy(deep=True) for t, df in raw.items()}
    result = BarEngine.build(raw, "time")

    # Input is untouched...
    for t in raw:
        pd.testing.assert_frame_equal(raw[t], snapshot[t])
    # ...and the result is a distinct object (mutating output can't affect input).
    some = next(iter(result.data.values()))
    some.iloc[0, some.columns.get_loc("Close")] = -999.0
    for t in raw:
        pd.testing.assert_frame_equal(raw[t], snapshot[t])


# ===========================================================================
# 3. Determinism — same inputs → identical outputs
# ===========================================================================

def test_build_is_deterministic():
    raw = _make_data_dict()
    r1 = BarEngine.build(raw, SamplingSpec("time"))
    r2 = BarEngine.build(raw, SamplingSpec("time"))
    assert set(r1.data) == set(r2.data)
    for t in r1.data:
        pd.testing.assert_frame_equal(r1.data[t], r2.data[t])
    assert r1.periods_per_year == r2.periods_per_year
    assert r1.diagnostics["total_bars"] == r2.diagnostics["total_bars"]


# ===========================================================================
# 4. Future-proof API — string, spec, and None are equivalent for time
# ===========================================================================

def test_api_accepts_str_spec_and_none():
    raw = _make_data_dict()
    via_none = build(raw).data
    via_str = build(raw, "time").data
    via_spec = build(raw, SamplingSpec(type="time")).data
    for t in raw:
        pd.testing.assert_frame_equal(via_none[t], via_str[t])
        pd.testing.assert_frame_equal(via_none[t], via_spec[t])


def test_bad_spec_type_argument_rejected():
    raw = _make_data_dict()
    with pytest.raises(TypeError):
        BarEngine.build(raw, 123)  # not SamplingSpec | str | None


# ===========================================================================
# 5. SamplingSpec vocabulary + immutability
# ===========================================================================

def test_sampling_spec_rejects_unknown_type():
    with pytest.raises(ValueError):
        SamplingSpec(type="renko")  # not yet in the vocabulary


def test_sampling_spec_is_immutable_and_params_readonly():
    spec = SamplingSpec(type="time", params={"k": 1})
    with pytest.raises(Exception):
        spec.type = "volume"           # frozen dataclass
    with pytest.raises(Exception):
        spec.params["k"] = 2           # read-only mapping


def test_from_bar_type_defaults_to_time():
    assert SamplingSpec.from_bar_type(None).type == "time"
    assert SamplingSpec.from_bar_type("").type == "time"
    assert SamplingSpec.from_bar_type("volume").type == "volume"


# ===========================================================================
# 6. Unimplemented-but-recognised bar types raise (never silently wrong)
# ===========================================================================

@pytest.mark.parametrize("bar_type", sorted(set(BAR_TYPES) - IMPLEMENTED_BAR_TYPES))
def test_unimplemented_bar_types_raise(bar_type):
    raw = _make_data_dict()
    with pytest.raises(NotImplementedError):
        BarEngine.build(raw, SamplingSpec(type=bar_type))


def test_time_is_the_only_implemented_type_in_be1():
    assert IMPLEMENTED_BAR_TYPES == frozenset({"time"})
    assert "time" in BAR_TYPES


# ===========================================================================
# 7. Annualisation cadence
# ===========================================================================

def test_periods_per_year_default_and_override():
    raw = _make_data_dict()
    assert BarEngine.build(raw, "time").periods_per_year == DEFAULT_PERIODS_PER_YEAR
    spec = SamplingSpec(type="time", periods_per_year=52.0)
    assert BarEngine.build(raw, spec).periods_per_year == 52.0


# ===========================================================================
# 8. Result shape + diagnostics
# ===========================================================================

def test_result_shape_and_diagnostics():
    raw = _make_data_dict(n_dates=50, n_tickers=4)
    result = BarEngine.build(raw, "time")
    assert isinstance(result, BarResult)
    assert result.sampling_spec.type == "time"
    d = result.diagnostics
    assert d["n_tickers"] == 4
    assert d["total_bars"] == 4 * 50
    assert d["bar_type"] == "time"
    assert d["identity"] is True
    assert d["quality_warnings"] == []


# ===========================================================================
# 9. Validation — structural violations raise; quality issues warn
# ===========================================================================

def test_validate_rejects_empty_and_missing_columns():
    with pytest.raises(BarValidationError):
        validate_bars({})
    bad = {"T00": pd.DataFrame({"Close": [1.0]},
                               index=pd.DatetimeIndex(["2020-01-02"], name="Date"))}
    with pytest.raises(BarValidationError):
        validate_bars(bad)  # missing OHLV


def test_validate_rejects_non_datetime_index():
    df = pd.DataFrame({c: [1.0, 2.0] for c in ("Open", "High", "Low", "Close", "Volume")})
    with pytest.raises(BarValidationError):
        validate_bars({"T00": df})  # RangeIndex, not DatetimeIndex


def test_validate_flags_unsorted_index_as_warning_not_error():
    idx = pd.DatetimeIndex(["2020-01-03", "2020-01-02"], name="Date")
    df = pd.DataFrame({c: [1.0, 1.0] for c in ("Open", "High", "Low", "Close", "Volume")}, index=idx)
    diag = validate_bars({"T00": df})  # does not raise
    assert any("monotonic" in w for w in diag["quality_warnings"])
