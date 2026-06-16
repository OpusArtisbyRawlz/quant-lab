"""Tests for spec_validator.py."""

import pytest
from pathlib import Path

from agents.protocol import ExperimentSpec
from agents.experiment_runner.spec_validator import validate_spec, KNOWN_SIGNALS


def _spec(**overrides) -> ExperimentSpec:
    """Minimal valid spec with overrides."""
    base = dict(
        hypothesis="Test hypothesis",
        market="US",
        universe="test_universe",
        target="fwd_ret_5",
        features=["mr_ret_10"],
        model="quantile_ranking",
        validation_method="walk_forward",
        success_criteria={"sharpe": 0.5},
        expected_improvement="baseline",
        project="test",
    )
    base.update(overrides)
    return ExperimentSpec(**base)


@pytest.fixture
def universe_dir(tmp_path):
    d = tmp_path / "test_universe"
    d.mkdir()
    (d / "aapl_us_d.csv").write_text("Date,Open,High,Low,Close,Volume\n2020-01-01,100,101,99,100,1000\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Valid spec
# ---------------------------------------------------------------------------

def test_valid_spec_passes(universe_dir):
    result = validate_spec(_spec(), data_root=universe_dir)
    assert result.valid
    assert result.errors == []


def test_valid_spec_no_errors(universe_dir):
    result = validate_spec(_spec(), data_root=universe_dir)
    assert not result.errors


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

def test_empty_hypothesis_is_error(universe_dir):
    result = validate_spec(_spec(hypothesis=""), data_root=universe_dir)
    assert not result.valid
    assert any("hypothesis" in e for e in result.errors)


def test_empty_market_is_error(universe_dir):
    result = validate_spec(_spec(market=""), data_root=universe_dir)
    assert not result.valid
    assert any("market" in e for e in result.errors)


def test_empty_model_is_error(universe_dir):
    result = validate_spec(_spec(model=""), data_root=universe_dir)
    assert not result.valid
    assert any("model" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Features / signals
# ---------------------------------------------------------------------------

def test_empty_features_is_error(universe_dir):
    result = validate_spec(_spec(features=[]), data_root=universe_dir)
    assert not result.valid
    assert any("features" in e for e in result.errors)


def test_unknown_signal_is_error(universe_dir):
    result = validate_spec(_spec(features=["not_a_real_signal"]), data_root=universe_dir)
    assert not result.valid
    assert any("Unknown signal" in e for e in result.errors)


def test_multiple_unknown_signals_listed(universe_dir):
    result = validate_spec(_spec(features=["bogus_a", "bogus_b"]), data_root=universe_dir)
    assert not result.valid
    assert any("bogus_a" in e and "bogus_b" in e for e in result.errors)


def test_all_known_signals_are_valid(universe_dir):
    for signal in KNOWN_SIGNALS:
        result = validate_spec(_spec(features=[signal]), data_root=universe_dir)
        assert result.valid, f"Expected {signal} to be valid, got errors: {result.errors}"


def test_multi_signal_combo_is_valid(universe_dir):
    result = validate_spec(
        _spec(features=["mr_ret_10", "low_vol_20", "mr_lowvol_blend"]),
        data_root=universe_dir,
    )
    assert result.valid


# ---------------------------------------------------------------------------
# Data directory checks
# ---------------------------------------------------------------------------

def test_missing_universe_dir_is_error(tmp_path):
    result = validate_spec(_spec(), data_root=tmp_path)  # test_universe does not exist
    assert not result.valid
    assert any("not found" in e for e in result.errors)


def test_empty_universe_dir_is_error(tmp_path):
    (tmp_path / "test_universe").mkdir()  # exists but no CSVs
    result = validate_spec(_spec(), data_root=tmp_path)
    assert not result.valid
    assert any("No CSV" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Warnings (soft checks)
# ---------------------------------------------------------------------------

def test_empty_success_criteria_is_warning(universe_dir):
    result = validate_spec(_spec(success_criteria={}), data_root=universe_dir)
    assert result.valid          # still valid
    assert any("success_criteria" in w for w in result.warnings)


def test_unknown_validation_method_is_warning(universe_dir):
    result = validate_spec(_spec(validation_method="made_up_method"), data_root=universe_dir)
    assert result.valid
    assert any("validation_method" in w for w in result.warnings)


def test_known_validation_methods_produce_no_warning(universe_dir):
    for method in ("walk_forward", "expanding_window", "hold_out", "cross_val", "none"):
        result = validate_spec(_spec(validation_method=method), data_root=universe_dir)
        assert not any("validation_method" in w for w in result.warnings), method


def test_duplicate_experiment_id_is_warning(universe_dir):
    (universe_dir / "exp_001_test").mkdir()
    result = validate_spec(
        _spec(experiment_id="exp_001_test"),
        data_root=universe_dir,
        completed_dir=universe_dir,
    )
    assert result.valid
    assert any("already exists" in w for w in result.warnings)


def test_new_experiment_id_no_warning(universe_dir):
    result = validate_spec(
        _spec(experiment_id="exp_999_new"),
        data_root=universe_dir,
        completed_dir=universe_dir,
    )
    assert not any("already exists" in w for w in result.warnings)
