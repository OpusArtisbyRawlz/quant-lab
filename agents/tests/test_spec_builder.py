"""
Tests for idea_generator/spec_builder.py — pure idea_row -> ExperimentSpec.

No I/O. Verifies that market/universe/hypothesis/signals come FROM the idea row
(self-contained reproduction) and that target/model/validation_method mirror the
Experiment Designer defaults, so idea-sourced specs match hand-authored ones.
"""

from agents.protocol import ExperimentSpec
from agents.idea_generator.spec_builder import (
    idea_to_spec,
    _DEFAULT_MODEL,
    _DEFAULT_TARGET,
    _DEFAULT_VALIDATION_METHOD,
    _DEFAULT_SUCCESS_CRITERIA,
)


def _idea_row(**overrides) -> dict:
    base = dict(
        idea_id="idea_001_calm_regimes",
        hypothesis="Calm regimes strengthen momentum",
        market="us",
        universe="sp500",
        suggested_signals=["mom_ret_20", "low_vol_20"],
        source_model="fake-idea-llm",
    )
    base.update(overrides)
    return base


def test_returns_experiment_spec():
    spec = idea_to_spec(_idea_row())
    assert isinstance(spec, ExperimentSpec)


def test_market_universe_come_from_idea():
    spec = idea_to_spec(_idea_row(market="eu", universe="stoxx600"))
    assert spec.market == "eu"
    assert spec.universe == "stoxx600"


def test_hypothesis_and_signals_preserved():
    spec = idea_to_spec(_idea_row())
    assert spec.hypothesis == "Calm regimes strengthen momentum"
    assert spec.features == ["mom_ret_20", "low_vol_20"]


def test_designer_defaults_applied():
    spec = idea_to_spec(_idea_row())
    assert spec.target == _DEFAULT_TARGET
    assert spec.model == _DEFAULT_MODEL
    assert spec.validation_method == _DEFAULT_VALIDATION_METHOD


def test_default_success_criteria_used_when_absent():
    spec = idea_to_spec(_idea_row())
    assert spec.success_criteria == _DEFAULT_SUCCESS_CRITERIA


def test_success_criteria_override_respected():
    spec = idea_to_spec(_idea_row(), success_criteria={"sharpe": 0.9})
    assert spec.success_criteria == {"sharpe": 0.9}


def test_provenance_recorded_in_notes():
    spec = idea_to_spec(_idea_row())
    assert "idea_001_calm_regimes" in spec.notes
    assert "fake-idea-llm" in spec.notes


def test_missing_market_universe_fall_back_to_unknown():
    spec = idea_to_spec(_idea_row(market="", universe=""))
    assert spec.market == "unknown"
    assert spec.universe == "unknown"


def test_signals_as_json_string_are_deserialized():
    spec = idea_to_spec(_idea_row(suggested_signals='["mr_ret_5", "low_vol_20"]'))
    assert spec.features == ["mr_ret_5", "low_vol_20"]


def test_no_signals_yields_empty_features():
    row = _idea_row()
    del row["suggested_signals"]
    spec = idea_to_spec(row)
    assert spec.features == []


def test_project_defaults_to_idea_generator():
    spec = idea_to_spec(_idea_row())
    assert spec.project == "idea_generator"
