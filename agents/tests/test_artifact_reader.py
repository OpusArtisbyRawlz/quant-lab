"""
Tests for artifact_reader.py.

Fixtures simulate the real variation found across experiment folders:
- fully populated folder (metrics + config + summary + strategy CSV)
- metrics only
- config only
- strategy CSV only
- completely empty folder
- malformed JSON
- empty files
- strategy CSV with missing/non-numeric cells
- YAML config (with and without pyyaml installed)
- classification experiment (auc/accuracy metrics)
- regression experiment (mse/r2 metrics)
- risk overlay experiment (calmar/avg_exposure metrics)
"""

import json
import pytest
from pathlib import Path

from agents.quant_interface.artifact_reader import (
    ArtifactBundle,
    StrategyVariant,
    read_experiment_artifact,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def full_exp(tmp_path) -> Path:
    d = tmp_path / "exp_full"
    d.mkdir()
    (d / "metrics.json").write_text(
        json.dumps({"sharpe": 1.54, "mdd": -0.655, "cagr": 0.426, "vol": 0.25, "calmar": 0.65})
    )
    (d / "config.json").write_text(
        json.dumps({"model": "quantile_ranking", "horizon": 5})
    )
    (d / "results_summary.md").write_text("Strong result. Sharpe 1.54.")
    (d / "notes.md").write_text("Tried blending LS20 + LS30.")
    (d / "strategy_comparison.csv").write_text(
        "Strategy,Sharpe,MDD,CAGR,Vol,Calmar\n"
        "LS 20%,1.516,-0.655,0.425,0.255,0.648\n"
        "LS 30%,1.20,-0.50,0.35,0.22,0.55\n"
    )
    return d


@pytest.fixture
def metrics_only(tmp_path) -> Path:
    d = tmp_path / "exp_metrics_only"
    d.mkdir()
    (d / "metrics.json").write_text(json.dumps({"sharpe": 0.85, "mdd": -0.30}))
    return d


@pytest.fixture
def config_only(tmp_path) -> Path:
    d = tmp_path / "exp_config_only"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"model": "logistic_regression"}))
    return d


@pytest.fixture
def strategy_csv_only(tmp_path) -> Path:
    d = tmp_path / "exp_strategy_only"
    d.mkdir()
    (d / "strategy_comparison.csv").write_text(
        "Strategy,Sharpe,MDD,CAGR,Vol,Calmar\n"
        "Blend 60/40,1.515,-0.625,0.39,0.236,0.624\n"
    )
    return d


@pytest.fixture
def empty_folder(tmp_path) -> Path:
    d = tmp_path / "exp_empty"
    d.mkdir()
    return d


@pytest.fixture
def malformed_json(tmp_path) -> Path:
    d = tmp_path / "exp_bad_json"
    d.mkdir()
    (d / "metrics.json").write_text("{bad json,,,}")
    (d / "results_summary.md").write_text("Some summary text.")
    return d


@pytest.fixture
def empty_files(tmp_path) -> Path:
    d = tmp_path / "exp_empty_files"
    d.mkdir()
    (d / "metrics.json").write_text("")
    (d / "config.json").write_text("")
    (d / "results_summary.md").write_text("")
    return d


@pytest.fixture
def partial_csv(tmp_path) -> Path:
    """CSV with some blank/non-numeric cells."""
    d = tmp_path / "exp_partial_csv"
    d.mkdir()
    (d / "strategy_comparison.csv").write_text(
        "Strategy,Sharpe,MDD,CAGR,Vol,Calmar\n"
        "Good Strategy,1.2,-0.3,0.2,0.15,0.8\n"
        "Bad Row,,,-0.1,,\n"
        ",1.0,-0.2,,,\n"            # empty strategy name → skipped
    )
    return d


@pytest.fixture
def alt_summary_name(tmp_path) -> Path:
    """Uses result_summary.md (alternate filename)."""
    d = tmp_path / "exp_alt_summary"
    d.mkdir()
    (d / "result_summary.md").write_text("Alternative summary filename.")
    return d


@pytest.fixture
def classification_exp(tmp_path) -> Path:
    d = tmp_path / "exp_classification"
    d.mkdir()
    (d / "metrics.json").write_text(
        json.dumps({"model": "logistic_regression", "auc": 0.539,
                    "accuracy": 0.586, "precision": 0.588, "recall": 0.992})
    )
    (d / "config.json").write_text(json.dumps({"model": "logistic_regression"}))
    return d


@pytest.fixture
def regression_exp(tmp_path) -> Path:
    d = tmp_path / "exp_regression"
    d.mkdir()
    (d / "metrics.json").write_text(
        json.dumps({"mse": 0.0042, "mae": 0.048, "r2": 0.12})
    )
    return d


@pytest.fixture
def risk_overlay_exp(tmp_path) -> Path:
    d = tmp_path / "exp_risk_overlay"
    d.mkdir()
    (d / "metrics.json").write_text(
        json.dumps({"sharpe": 2.09, "calmar": 1.03, "avg_exposure": 0.80, "mdd": -0.37})
    )
    (d / "config.json").write_text(
        json.dumps({"final_model": "smooth_drawdown_exposure", "k": 5, "floor": 0.55})
    )
    return d


@pytest.fixture
def final_summary_csv(tmp_path) -> Path:
    """Uses final_project05_summary.csv instead of strategy_comparison.csv."""
    d = tmp_path / "exp_final_summary"
    d.mkdir()
    (d / "final_project05_summary.csv").write_text(
        "Strategy,Sharpe,MDD,CAGR,Vol,Calmar,Avg_Exposure\n"
        "Weighted multi-strategy + smooth DD,1.851,-0.476,0.384,0.185,0.807,1.0\n"
    )
    return d


# ---------------------------------------------------------------------------
# Full folder
# ---------------------------------------------------------------------------

def test_full_bundle_reads_all_fields(full_exp):
    b = read_experiment_artifact(full_exp)
    assert b.metrics is not None
    assert b.config is not None
    assert b.summary_text is not None
    assert b.notes_text is not None
    assert len(b.strategy_variants) == 2


def test_full_bundle_metrics_values(full_exp):
    b = read_experiment_artifact(full_exp)
    assert abs(b.metrics["sharpe"] - 1.54) < 1e-6
    assert abs(b.metrics["mdd"] - (-0.655)) < 1e-6


def test_full_bundle_config_values(full_exp):
    b = read_experiment_artifact(full_exp)
    assert b.config["model"] == "quantile_ranking"


def test_full_bundle_strategy_variants(full_exp):
    b = read_experiment_artifact(full_exp)
    names = [v.strategy_name for v in b.strategy_variants]
    assert "LS 20%" in names
    sharpes = [v.sharpe for v in b.strategy_variants if v.strategy_name == "LS 20%"]
    assert abs(sharpes[0] - 1.516) < 1e-6


def test_full_bundle_best_sharpe(full_exp):
    b = read_experiment_artifact(full_exp)
    assert abs(b.best_sharpe() - 1.516) < 1e-6


def test_full_bundle_no_warnings(full_exp):
    b = read_experiment_artifact(full_exp)
    assert b.warnings == []


def test_full_bundle_files_found(full_exp):
    b = read_experiment_artifact(full_exp)
    assert "metrics.json" in b.files_found
    assert "config.json" in b.files_found
    assert "strategy_comparison.csv" in b.files_found


def test_full_bundle_not_empty(full_exp):
    b = read_experiment_artifact(full_exp)
    assert not b.is_empty


# ---------------------------------------------------------------------------
# Partial folders
# ---------------------------------------------------------------------------

def test_metrics_only(metrics_only):
    b = read_experiment_artifact(metrics_only)
    assert b.metrics is not None
    assert b.config is None
    assert b.summary_text is None
    assert b.strategy_variants == []
    assert not b.is_empty


def test_config_only(config_only):
    b = read_experiment_artifact(config_only)
    assert b.config is not None
    assert b.metrics is None
    assert not b.is_empty


def test_strategy_csv_only(strategy_csv_only):
    b = read_experiment_artifact(strategy_csv_only)
    assert len(b.strategy_variants) == 1
    assert b.strategy_variants[0].strategy_name == "Blend 60/40"
    assert not b.is_empty


def test_best_sharpe_from_variants_when_no_metrics(strategy_csv_only):
    b = read_experiment_artifact(strategy_csv_only)
    assert b.metrics is None
    assert abs(b.best_sharpe() - 1.515) < 1e-6


# ---------------------------------------------------------------------------
# Empty folder
# ---------------------------------------------------------------------------

def test_empty_folder_is_empty(empty_folder):
    b = read_experiment_artifact(empty_folder)
    assert b.is_empty
    assert b.metrics is None
    assert b.config is None
    assert b.strategy_variants == []


def test_empty_folder_files_missing(empty_folder):
    b = read_experiment_artifact(empty_folder)
    assert "metrics.json" in b.files_missing


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_malformed_json_produces_warning_not_exception(malformed_json):
    b = read_experiment_artifact(malformed_json)
    assert b.metrics is None
    assert any("parse error" in w for w in b.warnings)


def test_malformed_json_still_reads_summary(malformed_json):
    b = read_experiment_artifact(malformed_json)
    assert b.summary_text == "Some summary text."


def test_empty_files_produce_warnings(empty_files):
    b = read_experiment_artifact(empty_files)
    assert b.metrics is None
    assert b.config is None
    assert b.summary_text is None
    assert any("empty" in w for w in b.warnings)


def test_partial_csv_skips_empty_strategy_name(partial_csv):
    b = read_experiment_artifact(partial_csv)
    names = [v.strategy_name for v in b.strategy_variants]
    assert "" not in names
    assert "Good Strategy" in names


def test_partial_csv_tolerates_blank_numeric_cells(partial_csv):
    b = read_experiment_artifact(partial_csv)
    bad_row = next((v for v in b.strategy_variants if v.strategy_name == "Bad Row"), None)
    assert bad_row is not None
    # sharpe and mdd are blank in the fixture → None
    assert bad_row.sharpe is None
    assert bad_row.mdd is None
    # cagr is -0.1 in the fixture — a valid float, correctly parsed
    assert bad_row.cagr == pytest.approx(-0.1)
    # vol and calmar are blank → None
    assert bad_row.vol is None
    assert bad_row.calmar is None


# ---------------------------------------------------------------------------
# Alternate file names
# ---------------------------------------------------------------------------

def test_alt_summary_filename(alt_summary_name):
    b = read_experiment_artifact(alt_summary_name)
    assert b.summary_text == "Alternative summary filename."


def test_final_summary_csv_is_read(final_summary_csv):
    b = read_experiment_artifact(final_summary_csv)
    assert len(b.strategy_variants) == 1
    v = b.strategy_variants[0]
    assert "smooth DD" in v.strategy_name
    assert abs(v.sharpe - 1.851) < 1e-6
    assert v.avg_exposure == 1.0


# ---------------------------------------------------------------------------
# experiment_id is taken from folder name
# ---------------------------------------------------------------------------

def test_experiment_id_from_folder_name(full_exp):
    b = read_experiment_artifact(full_exp)
    assert b.experiment_id == "exp_full"


def test_artifact_path_recorded(full_exp):
    b = read_experiment_artifact(full_exp)
    assert b.artifact_path == full_exp


# ---------------------------------------------------------------------------
# Experiment type detection
# ---------------------------------------------------------------------------

def test_type_portfolio_from_strategy_csv(strategy_csv_only):
    b = read_experiment_artifact(strategy_csv_only)
    assert b.experiment_type == "portfolio"


def test_type_portfolio_from_metrics_keys(full_exp):
    b = read_experiment_artifact(full_exp)
    assert b.experiment_type == "portfolio"


def test_type_classification_from_auc(classification_exp):
    b = read_experiment_artifact(classification_exp)
    assert b.experiment_type == "classification"


def test_type_classification_metrics_preserved(classification_exp):
    b = read_experiment_artifact(classification_exp)
    assert b.metrics is not None
    assert "auc" in b.metrics
    assert abs(b.metrics["auc"] - 0.539) < 1e-6
    assert "accuracy" in b.metrics


def test_type_regression_from_mse(regression_exp):
    b = read_experiment_artifact(regression_exp)
    assert b.experiment_type == "regression"


def test_type_regression_metrics_preserved(regression_exp):
    b = read_experiment_artifact(regression_exp)
    assert b.metrics is not None
    assert "mse" in b.metrics
    assert "r2" in b.metrics


def test_type_risk_overlay_from_calmar_and_exposure(risk_overlay_exp):
    b = read_experiment_artifact(risk_overlay_exp)
    assert b.experiment_type == "risk_overlay"


def test_type_risk_overlay_config_hint():
    """drawdown in model name → risk_overlay even without avg_exposure key."""
    from agents.quant_interface.artifact_reader import detect_experiment_type
    result = detect_experiment_type(
        metrics={"sharpe": 2.0, "mdd": -0.3},    # no calmar/avg_exposure
        config={"final_model": "smooth_drawdown_overlay"},
        has_strategy_variants=False,
    )
    assert result == "risk_overlay"


def test_type_unknown_when_no_evidence(empty_folder):
    b = read_experiment_artifact(empty_folder)
    assert b.experiment_type == "unknown"


def test_type_detection_is_best_effort_not_exception():
    """detect_experiment_type never raises."""
    from agents.quant_interface.artifact_reader import detect_experiment_type
    result = detect_experiment_type(metrics=None, config=None, has_strategy_variants=False)
    assert result == "unknown"
