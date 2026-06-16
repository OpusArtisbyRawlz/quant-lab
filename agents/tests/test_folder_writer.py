"""Tests for experiment_runner/folder_writer.py."""

import json
import pytest
from pathlib import Path

from agents.protocol import ExperimentSpec
from agents.experiment_runner.folder_writer import (
    make_experiment_id,
    create_experiment_folder,
    write_config_json,
    write_results_summary,
    write_error_txt,
    _next_sequence_number,
    _make_slug,
)


def _spec(**overrides) -> ExperimentSpec:
    base = dict(
        hypothesis="Does mr_ret_10 work?",
        market="US",
        universe="project_04_universe",
        target="fwd_ret_5",
        features=["mr_ret_10", "low_vol_20"],
        model="quantile_ranking",
        validation_method="walk_forward",
        success_criteria={"sharpe": 0.6},
        expected_improvement="+0.1 Sharpe",
        project="project06",
        notes="",
    )
    base.update(overrides)
    return ExperimentSpec(**base)


# ---------------------------------------------------------------------------
# _next_sequence_number
# ---------------------------------------------------------------------------

def test_next_sequence_empty_dir(tmp_path):
    assert _next_sequence_number(tmp_path) == 1


def test_next_sequence_missing_dir(tmp_path):
    assert _next_sequence_number(tmp_path / "missing") == 1


def test_next_sequence_existing_experiments(tmp_path):
    for name in ["exp_001_foo", "exp_003_bar", "exp_007_baz"]:
        (tmp_path / name).mkdir()
    assert _next_sequence_number(tmp_path) == 8


def test_next_sequence_ignores_non_exp_dirs(tmp_path):
    (tmp_path / "archive").mkdir()
    (tmp_path / "exp_002_foo").mkdir()
    assert _next_sequence_number(tmp_path) == 3


# ---------------------------------------------------------------------------
# _make_slug
# ---------------------------------------------------------------------------

def test_make_slug_combines_project_and_model():
    spec = _spec(project="project06", model="quantile_ranking")
    assert _make_slug(spec) == "project06_quantile_ranking"


def test_make_slug_no_project():
    spec = _spec(project="", model="quantile_ranking")
    assert _make_slug(spec) == "quantile_ranking"


def test_make_slug_lowercase():
    spec = _spec(project="ProjectX", model="MyModel")
    assert _make_slug(spec) == _make_slug(spec).lower()


def test_make_slug_spaces_become_underscores():
    spec = _spec(project="my project", model="some model")
    slug = _make_slug(spec)
    assert " " not in slug


def test_make_slug_max_40_chars():
    spec = _spec(project="a" * 30, model="b" * 30)
    assert len(_make_slug(spec)) <= 40


# ---------------------------------------------------------------------------
# make_experiment_id
# ---------------------------------------------------------------------------

def test_make_experiment_id_respects_preset_id(tmp_path):
    spec = _spec(experiment_id="exp_999_custom")
    assert make_experiment_id(spec, tmp_path) == "exp_999_custom"


def test_make_experiment_id_auto_assigns(tmp_path):
    spec = _spec()
    eid = make_experiment_id(spec, tmp_path)
    assert eid.startswith("exp_001_")


def test_make_experiment_id_increments(tmp_path):
    (tmp_path / "exp_004_existing").mkdir()
    spec = _spec()
    eid = make_experiment_id(spec, tmp_path)
    assert eid.startswith("exp_005_")


def test_make_experiment_id_format(tmp_path):
    spec = _spec()
    eid = make_experiment_id(spec, tmp_path)
    parts = eid.split("_")
    assert parts[0] == "exp"
    assert parts[1].isdigit() and len(parts[1]) == 3


# ---------------------------------------------------------------------------
# create_experiment_folder
# ---------------------------------------------------------------------------

def test_create_experiment_folder_creates_dir(tmp_path):
    folder = create_experiment_folder("exp_001_test", tmp_path)
    assert folder.exists()
    assert folder.is_dir()


def test_create_experiment_folder_returns_path(tmp_path):
    folder = create_experiment_folder("exp_001_test", tmp_path)
    assert folder == tmp_path / "exp_001_test"


def test_create_experiment_folder_raises_on_existing(tmp_path):
    create_experiment_folder("exp_001_test", tmp_path)
    with pytest.raises(FileExistsError):
        create_experiment_folder("exp_001_test", tmp_path)


# ---------------------------------------------------------------------------
# write_config_json
# ---------------------------------------------------------------------------

def test_write_config_json_creates_file(tmp_path):
    spec = _spec()
    write_config_json(tmp_path, spec, "exp_001_test")
    assert (tmp_path / "config.json").exists()


def test_write_config_json_contains_experiment_id(tmp_path):
    spec = _spec()
    write_config_json(tmp_path, spec, "exp_001_test")
    data = json.loads((tmp_path / "config.json").read_text())
    assert data["experiment_id"] == "exp_001_test"


def test_write_config_json_contains_features(tmp_path):
    spec = _spec()
    write_config_json(tmp_path, spec, "exp_001_test")
    data = json.loads((tmp_path / "config.json").read_text())
    assert data["features"] == ["mr_ret_10", "low_vol_20"]


def test_write_config_json_contains_generated_at(tmp_path):
    spec = _spec()
    write_config_json(tmp_path, spec, "exp_001_test")
    data = json.loads((tmp_path / "config.json").read_text())
    assert "generated_at" in data


# ---------------------------------------------------------------------------
# write_results_summary
# ---------------------------------------------------------------------------

def test_write_results_summary_creates_file(tmp_path):
    spec = _spec()
    metrics = {"sharpe": 1.2, "mdd": -0.3, "cagr": 0.15, "vol": 0.12, "calmar": 0.5}
    write_results_summary(tmp_path, metrics, spec, "exp_001_test")
    assert (tmp_path / "results_summary.md").exists()


def test_write_results_summary_contains_experiment_id(tmp_path):
    spec = _spec()
    metrics = {"sharpe": 1.2, "mdd": -0.3, "cagr": 0.15, "vol": 0.12, "calmar": 0.5}
    write_results_summary(tmp_path, metrics, spec, "exp_001_test")
    text = (tmp_path / "results_summary.md").read_text()
    assert "exp_001_test" in text


def test_write_results_summary_contains_metrics(tmp_path):
    spec = _spec()
    metrics = {"sharpe": 1.2, "mdd": -0.3, "cagr": 0.15, "vol": 0.12, "calmar": 0.5}
    write_results_summary(tmp_path, metrics, spec, "exp_001_test")
    text = (tmp_path / "results_summary.md").read_text()
    assert "1.2000" in text
    assert "SHARPE" in text.upper()


def test_write_results_summary_none_metrics_shows_na(tmp_path):
    spec = _spec()
    metrics = {"sharpe": None, "mdd": None, "cagr": None, "vol": None, "calmar": None}
    write_results_summary(tmp_path, metrics, spec, "exp_001_test")
    text = (tmp_path / "results_summary.md").read_text()
    assert "N/A" in text


def test_write_results_summary_success_criteria_section(tmp_path):
    spec = _spec(success_criteria={"sharpe": 0.6})
    metrics = {"sharpe": 1.2, "mdd": -0.3, "cagr": 0.15, "vol": 0.12, "calmar": 0.5}
    write_results_summary(tmp_path, metrics, spec, "exp_001_test")
    text = (tmp_path / "results_summary.md").read_text()
    assert "Success Criteria" in text


# ---------------------------------------------------------------------------
# write_error_txt
# ---------------------------------------------------------------------------

def test_write_error_txt_creates_file(tmp_path):
    write_error_txt(tmp_path, "Something went wrong")
    assert (tmp_path / "error.txt").exists()


def test_write_error_txt_contains_message(tmp_path):
    write_error_txt(tmp_path, "ZeroDivisionError: division by zero")
    text = (tmp_path / "error.txt").read_text()
    assert "ZeroDivisionError" in text


def test_write_error_txt_contains_timestamp(tmp_path):
    write_error_txt(tmp_path, "err")
    text = (tmp_path / "error.txt").read_text()
    assert "Run failed at" in text
