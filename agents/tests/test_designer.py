"""Tests for agents/experiment_designer/designer.py."""

import pytest
from pathlib import Path

from agents.protocol import ExperimentSpec, HypothesisTask
from agents.experiment_designer.designer import ExperimentDesigner, DesignError
from agents.experiment_runner.spec_validator import KNOWN_SIGNALS


def _task(**overrides) -> HypothesisTask:
    base = dict(
        hypothesis="mr_ret_5 mean-reversion works on short horizons",
        suggested_signals=["mr_ret_5"],
        project="project_test",
        universe="test_universe",
        market="US",
        priority=1,
    )
    base.update(overrides)
    return HypothesisTask(**base)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_designer_returns_experiment_spec(tmp_db):
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    assert isinstance(spec, ExperimentSpec)


def test_designer_features_from_suggested_signals(tmp_db):
    spec = ExperimentDesigner().run(_task(suggested_signals=["mr_ret_10"]), db_path=tmp_db)
    assert spec.features == ["mr_ret_10"]


def test_designer_uses_default_model(tmp_db):
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    assert spec.model == "quantile_ranking"


def test_designer_uses_default_target(tmp_db):
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    assert spec.target == "fwd_ret_5"


def test_designer_uses_default_validation_method(tmp_db):
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    assert spec.validation_method == "walk_forward"


def test_designer_propagates_hypothesis(tmp_db):
    spec = ExperimentDesigner().run(_task(hypothesis="Test hyp"), db_path=tmp_db)
    assert spec.hypothesis == "Test hyp"


def test_designer_propagates_project(tmp_db):
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    assert spec.project == "project_test"


def test_designer_propagates_universe(tmp_db):
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    assert spec.universe == "test_universe"


def test_designer_propagates_market(tmp_db):
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    assert spec.market == "US"


def test_designer_success_criteria_set(tmp_db):
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    assert "sharpe" in spec.success_criteria


# ---------------------------------------------------------------------------
# Signal resolution
# ---------------------------------------------------------------------------

def test_designer_falls_back_to_default_when_no_suggested_signals(tmp_db):
    spec = ExperimentDesigner().run(_task(suggested_signals=[]), db_path=tmp_db)
    assert len(spec.features) >= 1
    assert all(s in KNOWN_SIGNALS for s in spec.features)


def test_designer_falls_back_to_default_when_all_suggested_are_unknown(tmp_db):
    # Unknown signals are filtered out; Designer falls back to a default signal set.
    # This is resilient behaviour — it does NOT raise on unknown suggestions.
    spec = ExperimentDesigner().run(
        _task(suggested_signals=["bogus_signal_xyz"]),
        db_path=tmp_db,
    )
    assert len(spec.features) >= 1
    assert all(s in KNOWN_SIGNALS for s in spec.features)
    assert "bogus_signal_xyz" not in spec.features


def test_designer_filters_unknown_signals_uses_valid_remainder(tmp_db):
    # One valid + one invalid → uses the valid one
    spec = ExperimentDesigner().run(
        _task(suggested_signals=["mr_ret_5", "bogus_xyz"]),
        db_path=tmp_db,
    )
    assert "mr_ret_5" in spec.features
    assert "bogus_xyz" not in spec.features


def test_designer_multi_signal_combo(tmp_db):
    spec = ExperimentDesigner().run(
        _task(suggested_signals=["mr_ret_5", "low_vol_20"]),
        db_path=tmp_db,
    )
    assert spec.features == ["mr_ret_5", "low_vol_20"]


# ---------------------------------------------------------------------------
# Spec validity
# ---------------------------------------------------------------------------

def test_designer_spec_passes_validation(tmp_db):
    from agents.experiment_runner.spec_validator import validate_spec
    spec = ExperimentDesigner().run(_task(), db_path=tmp_db)
    result = validate_spec(spec, data_root=Path("."), skip_data_check=True)
    assert result.valid
