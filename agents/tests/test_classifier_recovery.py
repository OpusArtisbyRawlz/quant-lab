"""
Project 03 — single-asset directional classifier recovery.

Verifies the general classifier experiment path reproduces the historical P03 models
exactly and enters the factory as a distinct experiment type (classification), without
mixing into the return-based / M11 sharpe machinery.

Data-dependent tests skip when the git-ignored SPY.csv is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SPY = _REPO / "data" / "raw" / "SPY.csv"
_FEATS = ["ret_5", "ret_10", "ret_20", "ma_dist_20", "rv20", "volume_ratio"]


def test_classifier_spec_field_defaults_off_and_threads():
    from agents.protocol import ExperimentSpec
    from agents.idea_generator.spec_builder import idea_to_spec
    assert ExperimentSpec("h", "m", "u", "t", [], "mo", "none", {}, "").classifier is None
    row = {"hypothesis": "h", "market": "US_EQUITY", "universe": "SPY",
           "suggested_signals": _FEATS, "bar_type": "time",
           "metadata": {"classifier": {"asset": "SPY", "features": _FEATS,
                                        "model": "logistic", "horizon": 5}}}
    spec = idea_to_spec(row)
    assert spec.classifier["model"] == "logistic"


def test_classifier_spec_validation():
    from agents.protocol import ExperimentSpec
    from agents.experiment_runner.spec_validator import validate_spec
    good = ExperimentSpec("h", "US", "SPY", "dir", [], "logistic", "none", {"auc": 0.5},
                          "", classifier={"asset": "SPY", "features": _FEATS, "model": "logistic"})
    assert validate_spec(good, _REPO / "data" / "raw", skip_data_check=True).valid
    bad = ExperimentSpec("h", "US", "SPY", "dir", [], "x", "none", {}, "",
                         classifier={"asset": "SPY", "features": _FEATS, "model": "nope"})
    assert not validate_spec(bad, _REPO / "data" / "raw", skip_data_check=True).valid


@pytest.mark.skipif(not _SPY.exists(), reason="SPY.csv (git-ignored) absent")
@pytest.mark.parametrize("model,auc,acc", [
    ("logistic", 0.5389, 0.5863),
    ("random_forest", 0.5063, 0.5873),
    ("naive_up", None, 0.5892),
])
def test_classifier_fidelity(model, auc, acc):
    from src.classifier.directional import run_directional_classifier
    preds, m = run_directional_classifier(_SPY, features=_FEATS, horizon=5,
                                          model=model, split_fraction=0.8)
    assert m["n_test"] == 1054
    assert abs(m["accuracy"] - acc) < 0.005
    if auc is None:
        assert m["roc_auc"] is None            # constant baseline → AUC undefined
    else:
        assert abs(m["roc_auc"] - auc) < 0.005


@pytest.mark.skipif(not _SPY.exists(), reason="SPY.csv (git-ignored) absent")
def test_classifier_runs_through_factory_as_classification(tmp_path):
    from agents.protocol import ExperimentSpec
    from agents.experiment_runner import runner
    from agents.quant_interface.artifact_reader import detect_experiment_type
    spec = ExperimentSpec(
        hypothesis="SPY 5d direction", market="US_EQUITY", universe="SPY",
        target="direction_5d", features=[], model="logistic", validation_method="none",
        success_criteria={"auc": 0.5}, expected_improvement="", experiment_id="clf_test",
        classifier={"asset": "SPY", "features": _FEATS, "model": "logistic", "horizon": 5})
    r = runner.run_experiment(spec, db_path=tmp_path / "d.db",
                              completed_dir=tmp_path / "c", data_root=_REPO / "data" / "raw")
    assert r.status == "success"
    m = json.loads((tmp_path / "c" / "clf_test" / "metrics.json").read_text())
    # distinct experiment type; no portfolio/sharpe metrics produced
    assert detect_experiment_type(m, None, False) == "classification"
    assert "sharpe" not in m
    assert (tmp_path / "c" / "clf_test" / "predictions.csv").exists()
