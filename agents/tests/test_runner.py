"""
Tests for experiment_runner/runner.py.

All tests use synthetic DataFrames passed via data_dict= to avoid any
network calls, yfinance downloads, or reads from data/raw/.

The pipeline (run_market_alpha_pipeline + apply_signal_combo) is called
with synthetic data — we verify outputs structurally and statistically
rather than asserting exact metric values.
"""

import json
import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from agents.protocol import ExperimentSpec
from agents.experiment_runner.runner import run_experiment, RunResult
from agents.storage.db import create_all_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_data_dict(n_dates: int = 80, n_tickers: int = 10, seed: int = 42) -> dict:
    """
    Synthetic data_dict that can flow through the real src/ pipeline.
    Needs enough dates for rolling features: vol_20 (20), ma_20 (20),
    fwd_ret_5 (5), plus buffer → 80 dates.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    tickers = [f"T{i:02d}" for i in range(n_tickers)]

    data_dict = {}
    for ticker in tickers:
        prices = 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, n_dates))
        df = pd.DataFrame({
            "Open":   prices * rng.uniform(0.99, 1.00, n_dates),
            "High":   prices * rng.uniform(1.00, 1.01, n_dates),
            "Low":    prices * rng.uniform(0.98, 1.00, n_dates),
            "Close":  prices,
            "Volume": rng.integers(500_000, 2_000_000, n_dates).astype(float),
        }, index=dates)
        df.index.name = "Date"
        data_dict[ticker] = df

    return data_dict


def _spec(**overrides) -> ExperimentSpec:
    base = dict(
        hypothesis="Short-horizon mean-reversion works.",
        market="US",
        universe="test_universe",
        target="fwd_ret_5",
        features=["mr_ret_5"],
        model="quantile_ranking",
        validation_method="walk_forward",
        success_criteria={"sharpe": 0.3},
        expected_improvement="Positive Sharpe",
        project="project_test",
    )
    base.update(overrides)
    return ExperimentSpec(**base)


@pytest.fixture
def completed_dir(tmp_path):
    d = tmp_path / "completed"
    d.mkdir()
    return d


@pytest.fixture
def data_root(tmp_path):
    # data_root is not used when data_dict is supplied; provide a dummy
    d = tmp_path / "raw"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# RunResult structure
# ---------------------------------------------------------------------------

def test_run_experiment_returns_run_result(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert isinstance(result, RunResult)


def test_run_experiment_success_status(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert result.status == "success"


def test_run_experiment_assigns_experiment_id(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert result.experiment_id.startswith("exp_001_")


def test_run_experiment_respects_preset_id(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(experiment_id="exp_007_custom"),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert result.experiment_id == "exp_007_custom"


def test_run_experiment_has_metrics(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert "sharpe" in result.metrics
    assert "mdd" in result.metrics


def test_run_experiment_error_is_none_on_success(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert result.error is None


# ---------------------------------------------------------------------------
# Artifact files written
# ---------------------------------------------------------------------------

def test_artifact_folder_created(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert result.artifact_path is not None
    assert result.artifact_path.exists()


def test_metrics_json_written(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert (result.artifact_path / "metrics.json").exists()


def test_strategy_csv_written(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert (result.artifact_path / "strategy_comparison.csv").exists()


def test_strategy_csv_has_signal_combo_column(tmp_db, completed_dir, data_root):
    import csv
    result = run_experiment(
        _spec(features=["mr_ret_5", "low_vol_20"]),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    with open(result.artifact_path / "strategy_comparison.csv") as f:
        row = list(csv.DictReader(f))[0]
    assert "Signal Combo" in row
    assert row["Signal Combo"] == "mr_ret_5 + low_vol_20"


def test_config_json_written(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert (result.artifact_path / "config.json").exists()


def test_results_summary_md_written(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert (result.artifact_path / "results_summary.md").exists()


# ---------------------------------------------------------------------------
# SQLite ingestion
# ---------------------------------------------------------------------------

def test_experiment_row_written_to_db(tmp_db, completed_dir, data_root):
    from agents.storage.ledger_store import get_experiment
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    row = get_experiment(result.experiment_id, db_path=tmp_db)
    assert row is not None
    assert row["status"] == "completed"


def test_strategy_variant_written_to_db(tmp_db, completed_dir, data_root):
    from agents.quant_interface.ingestion import get_variants_for_experiment
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    variants = get_variants_for_experiment(result.experiment_id, db_path=tmp_db)
    assert len(variants) == 1


def test_variant_not_promoted_by_default(tmp_db, completed_dir, data_root):
    from agents.quant_interface.ingestion import get_variants_for_experiment
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    variants = get_variants_for_experiment(result.experiment_id, db_path=tmp_db)
    assert variants[0]["promoted_to_library"] == 0


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def test_dry_run_returns_dry_run_status(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
        dry_run=True,
    )
    assert result.status == "dry_run"


def test_dry_run_writes_no_files(tmp_db, completed_dir, data_root):
    run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
        dry_run=True,
    )
    assert not any(completed_dir.iterdir())


def test_dry_run_does_not_write_to_db(tmp_db, completed_dir, data_root):
    from agents.storage.ledger_store import get_experiment
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
        dry_run=True,
    )
    assert get_experiment(result.experiment_id, db_path=tmp_db) is None


# ---------------------------------------------------------------------------
# Invalid spec
# ---------------------------------------------------------------------------

def test_invalid_spec_returns_invalid_status(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(features=["not_a_real_signal"]),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert result.status == "invalid_spec"


def test_invalid_spec_writes_no_files(tmp_db, completed_dir, data_root):
    run_experiment(
        _spec(features=[]),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert not any(completed_dir.iterdir())


def test_invalid_spec_error_message_present(tmp_db, completed_dir, data_root):
    result = run_experiment(
        _spec(features=["bogus"]),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    assert result.error is not None
    assert "bogus" in result.error


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

def test_failed_run_writes_error_txt(tmp_db, completed_dir, data_root):
    # Pass empty data_dict to trigger pipeline failure
    result = run_experiment(
        _spec(),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict={},   # empty → pipeline will fail
    )
    assert result.status == "failed"
    assert result.artifact_path is not None
    assert (result.artifact_path / "error.txt").exists()


def test_failed_run_ingested_as_failed(tmp_db, completed_dir, data_root):
    from agents.storage.ledger_store import get_experiment
    result = run_experiment(
        _spec(experiment_id="exp_099_fail_test"),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict={},
    )
    # Folder is created and ingested even on failure
    row = get_experiment("exp_099_fail_test", db_path=tmp_db)
    assert row is not None


# ---------------------------------------------------------------------------
# Multi-signal combo
# ---------------------------------------------------------------------------

def test_multi_signal_combo_produces_one_variant(tmp_db, completed_dir, data_root):
    from agents.quant_interface.ingestion import get_variants_for_experiment
    result = run_experiment(
        _spec(features=["mr_ret_10", "low_vol_20", "mr_lowvol_blend"]),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    variants = get_variants_for_experiment(result.experiment_id, db_path=tmp_db)
    assert len(variants) == 1


def test_multi_signal_combo_strategy_name_in_csv(tmp_db, completed_dir, data_root):
    import csv
    result = run_experiment(
        _spec(features=["mr_ret_10", "low_vol_20"]),
        db_path=tmp_db,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=_make_data_dict(),
    )
    with open(result.artifact_path / "strategy_comparison.csv") as f:
        row = list(csv.DictReader(f))[0]
    assert row["Strategy"] == "mr_ret_10 + low_vol_20"


# ---------------------------------------------------------------------------
# Import boundary
# ---------------------------------------------------------------------------

def test_runner_does_not_expose_src_to_callers():
    """runner.py is allowed to import src/, but the public RunResult
    dataclass must not carry any src/ objects."""
    import inspect
    result_fields = {f.name for f in RunResult.__dataclass_fields__.values()}
    # All fields should be plain Python types — no pandas, no src objects
    assert "data_dict" not in result_fields
    assert "panel" not in result_fields


def test_no_src_import_outside_experiment_runner():
    """Decision-making agent modules must not import src/ directly."""
    import ast, os
    agent_root = Path(__file__).parent.parent
    allowed_dir = agent_root / "experiment_runner"

    violations = []
    for py_file in agent_root.rglob("*.py"):
        if py_file.is_relative_to(allowed_dir):
            continue
        if "test_" in py_file.name:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    module = ",".join(a.name for a in node.names)
                if module.startswith("src.") or module == "src":
                    violations.append(f"{py_file.relative_to(agent_root)}: imports {module!r}")

    assert violations == [], "src/ imported outside experiment_runner:\n" + "\n".join(violations)
