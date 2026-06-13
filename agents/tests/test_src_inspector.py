"""
Tests for src_inspector.py — introspection of existing quant-lab src/ library.

These tests work in two modes:
  - If the real src/ files exist (running from within quant-lab), they exercise
    the actual library content.
  - If src/ is missing (isolated test environment), inspectors return empty
    results with warnings — no exceptions.
"""

import pytest
from pathlib import Path

from agents.quant_interface.src_inspector import (
    inspect_all,
    list_available_signals,
    get_pipeline_params,
    list_metric_names,
    get_data_inventory,
    SignalDef,
    PipelineParams,
    DataInventory,
    SrcSummary,
    SIGNALS_LIB,
    PIPELINE,
    METRICS_MOD,
    DATA_RAW,
)

_SRC_AVAILABLE = SIGNALS_LIB.exists()
_PIPELINE_AVAILABLE = PIPELINE.exists()
_METRICS_AVAILABLE = METRICS_MOD.exists()
_DATA_AVAILABLE = DATA_RAW.exists()


# ---------------------------------------------------------------------------
# inspect_all — always returns SrcSummary, never raises
# ---------------------------------------------------------------------------

def test_inspect_all_returns_src_summary():
    result = inspect_all()
    assert isinstance(result, SrcSummary)


def test_inspect_all_never_raises():
    # Should not raise even if src/ files are missing
    result = inspect_all()
    assert result is not None


def test_inspect_all_warnings_is_list():
    result = inspect_all()
    assert isinstance(result.warnings, list)


# ---------------------------------------------------------------------------
# list_available_signals
# ---------------------------------------------------------------------------

def test_list_signals_returns_list():
    signals = list_available_signals()
    assert isinstance(signals, list)


def test_list_signals_missing_file_returns_empty_with_warning():
    warnings = []
    signals = list_available_signals.__wrapped__(warnings) if hasattr(list_available_signals, '__wrapped__') else None
    # Simpler: just check that calling with a non-existent path produces empty list
    from agents.quant_interface import src_inspector as si
    original = si.SIGNALS_LIB
    try:
        si.SIGNALS_LIB = Path("/nonexistent/library.py")
        w = []
        result = si.list_available_signals(w)
        assert result == []
        assert any("not found" in ww for ww in w)
    finally:
        si.SIGNALS_LIB = original


@pytest.mark.skipif(not _SRC_AVAILABLE, reason="src/signals/library.py not present")
def test_list_signals_finds_expected_signals():
    signals = list_available_signals()
    names = [s.name for s in signals]
    # These must exist in the current library
    for expected in ["mr_ret_5", "mom_ret_20", "low_vol_20", "mr_blend", "mom_blend"]:
        assert expected in names, f"Expected signal '{expected}' not found"


@pytest.mark.skipif(not _SRC_AVAILABLE, reason="src/signals/library.py not present")
def test_list_signals_all_have_signal_type():
    signals = list_available_signals()
    for s in signals:
        assert s.signal_type in (
            "momentum", "mean_reversion", "volatility", "composite", "unknown"
        ), f"Unexpected type '{s.signal_type}' for signal '{s.name}'"


@pytest.mark.skipif(not _SRC_AVAILABLE, reason="src/signals/library.py not present")
def test_list_signals_count():
    signals = list_available_signals()
    # library.py currently has 13 named signals
    assert len(signals) == 13


@pytest.mark.skipif(not _SRC_AVAILABLE, reason="src/signals/library.py not present")
def test_signal_types_classified_correctly():
    signals = list_available_signals()
    by_name = {s.name: s for s in signals}
    assert by_name["mr_ret_5"].signal_type == "mean_reversion"
    assert by_name["mom_ret_20"].signal_type == "momentum"
    assert by_name["low_vol_20"].signal_type == "volatility"
    assert by_name["mr_blend"].signal_type == "composite"


# ---------------------------------------------------------------------------
# get_pipeline_params
# ---------------------------------------------------------------------------

def test_pipeline_params_missing_file_returns_none():
    from agents.quant_interface import src_inspector as si
    original = si.PIPELINE
    try:
        si.PIPELINE = Path("/nonexistent/pipeline.py")
        w = []
        result = si.get_pipeline_params(w)
        assert result is None
        assert any("not found" in ww for ww in w)
    finally:
        si.PIPELINE = original


@pytest.mark.skipif(not _PIPELINE_AVAILABLE, reason="src/pipelines/cross_sectional.py not present")
def test_pipeline_params_returns_params_object():
    params = get_pipeline_params()
    assert isinstance(params, PipelineParams)


@pytest.mark.skipif(not _PIPELINE_AVAILABLE, reason="src/pipelines/cross_sectional.py not present")
def test_pipeline_params_has_signal_types():
    params = get_pipeline_params()
    assert len(params.valid_signal_types) > 0


@pytest.mark.skipif(not _PIPELINE_AVAILABLE, reason="src/pipelines/cross_sectional.py not present")
def test_pipeline_params_contains_known_signal_type():
    params = get_pipeline_params()
    assert any("mean_reversion" in st for st in params.valid_signal_types)


@pytest.mark.skipif(not _PIPELINE_AVAILABLE, reason="src/pipelines/cross_sectional.py not present")
def test_pipeline_params_horizons():
    params = get_pipeline_params()
    assert 5 in params.horizons


# ---------------------------------------------------------------------------
# list_metric_names
# ---------------------------------------------------------------------------

def test_metric_names_missing_file_returns_empty_with_warning():
    from agents.quant_interface import src_inspector as si
    original = si.METRICS_MOD
    try:
        si.METRICS_MOD = Path("/nonexistent/metrics.py")
        w = []
        result = si.list_metric_names(w)
        assert result == []
        assert any("not found" in ww for ww in w)
    finally:
        si.METRICS_MOD = original


@pytest.mark.skipif(not _METRICS_AVAILABLE, reason="src/utils/metrics.py not present")
def test_metric_names_returns_list_of_strings():
    names = list_metric_names()
    assert isinstance(names, list)
    assert all(isinstance(n, str) for n in names)


@pytest.mark.skipif(not _METRICS_AVAILABLE, reason="src/utils/metrics.py not present")
def test_metric_names_contains_expected_functions():
    names = list_metric_names()
    for expected in ["sharpe_ratio", "max_drawdown", "annualized_return", "annualized_volatility"]:
        assert expected in names


# ---------------------------------------------------------------------------
# get_data_inventory
# ---------------------------------------------------------------------------

def test_data_inventory_missing_dir_returns_missing_flag():
    from agents.quant_interface import src_inspector as si
    original = si.DATA_RAW
    try:
        si.DATA_RAW = Path("/nonexistent/raw")
        w = []
        inv = si.get_data_inventory(w)
        assert inv.missing is True
        assert inv.tickers == []
        assert any("not found" in ww for ww in w)
    finally:
        si.DATA_RAW = original


@pytest.mark.skipif(not _DATA_AVAILABLE, reason="data/raw/ not present")
def test_data_inventory_finds_tickers():
    inv = get_data_inventory()
    assert inv.file_count > 0
    assert len(inv.tickers) == inv.file_count


@pytest.mark.skipif(not _DATA_AVAILABLE, reason="data/raw/ not present")
def test_data_inventory_contains_spy():
    inv = get_data_inventory()
    assert "SPY" in inv.tickers or "spy" in [t.lower() for t in inv.tickers]


@pytest.mark.skipif(not _DATA_AVAILABLE, reason="data/raw/ not present")
def test_data_inventory_not_missing():
    inv = get_data_inventory()
    assert inv.missing is False


# ---------------------------------------------------------------------------
# Synthetic src files — pure unit tests that don't depend on real repo
# ---------------------------------------------------------------------------

def test_parse_signals_from_synthetic_source(tmp_path):
    from agents.quant_interface import src_inspector as si
    lib = tmp_path / "library.py"
    lib.write_text(
        'def get_signal_series(panel, signal_name):\n'
        '    if signal_name == "mom_ret_5":\n'
        '        return panel["ret_5"]\n'
        '    elif signal_name == "mr_ret_10":\n'
        '        return -panel["ret_10"]\n'
        '    else:\n'
        '        raise ValueError()\n'
    )
    original = si.SIGNALS_LIB
    try:
        si.SIGNALS_LIB = lib
        signals = si.list_available_signals()
        names = [s.name for s in signals]
        assert "mom_ret_5" in names
        assert "mr_ret_10" in names
    finally:
        si.SIGNALS_LIB = original


def test_parse_pipeline_from_synthetic_source(tmp_path):
    from agents.quant_interface import src_inspector as si
    pipe = tmp_path / "cross_sectional.py"
    pipe.write_text(
        'def run_market_alpha_pipeline(\n'
        '    data_dict, horizon: int = 10,\n'
        '    long_quantile: float = 0.8, short_quantile: float = 0.2,\n'
        '    signal_type: str = "my_signal",\n'
        ') -> None:\n'
        '    if signal_type == "type_a":\n'
        '        pass\n'
        '    elif signal_type == "type_b":\n'
        '        pass\n'
    )
    original = si.PIPELINE
    try:
        si.PIPELINE = pipe
        params = si.get_pipeline_params()
        assert params is not None
        assert "type_a" in params.valid_signal_types
        assert "type_b" in params.valid_signal_types
        assert params.horizons == [1, 5, 10, 20]
    finally:
        si.PIPELINE = original
