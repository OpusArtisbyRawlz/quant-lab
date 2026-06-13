"""
Tests for ingestion.py — experiment folder scanning and DB upsert.
"""

import json
import pytest
from pathlib import Path

from agents.storage.db import create_all_tables
from agents.quant_interface.ingestion import (
    ingest_all_completed,
    ingest_one,
    get_variants_for_experiment,
    get_unpromoted_variants,
    mark_variant_promoted,
)


def _make_exp(root: Path, name: str, **files) -> Path:
    """Helper: create an experiment folder with given file contents."""
    d = root / name
    d.mkdir(parents=True)
    for fname, content in files.items():
        (d / fname).write_text(content)
    return d


# ---------------------------------------------------------------------------
# ingest_one
# ---------------------------------------------------------------------------

def test_ingest_one_full_experiment(tmp_path, tmp_db):
    d = _make_exp(
        tmp_path, "exp_test_001",
        **{
            "metrics.json": json.dumps({"sharpe": 1.4, "mdd": -0.25, "cagr": 0.18}),
            "config.json": json.dumps({"model": "quantile_ranking"}),
            "results_summary.md": "Good result.",
            "strategy_comparison.csv": (
                "Strategy,Sharpe,MDD,CAGR,Vol,Calmar\n"
                "LS 20%,1.4,-0.25,0.18,0.13,0.72\n"
                "LS 30%,1.1,-0.20,0.14,0.12,0.55\n"
            ),
        },
    )
    result = ingest_one(d, db_path=tmp_db)
    assert result.status == "ingested"
    assert result.variants_written == 2
    assert result.error is None


def test_ingest_one_metrics_land_in_experiments_table(tmp_path, tmp_db):
    from agents.storage.ledger_store import get_experiment
    _make_exp(
        tmp_path, "exp_metrics_check",
        **{"metrics.json": json.dumps({"sharpe": 1.23, "mdd": -0.30})},
    )
    ingest_one(tmp_path / "exp_metrics_check", db_path=tmp_db)
    row = get_experiment("exp_metrics_check", db_path=tmp_db)
    assert row is not None
    assert abs(row["sharpe"] - 1.23) < 1e-6


def test_ingest_one_uses_best_variant_sharpe_when_no_metrics(tmp_path, tmp_db):
    from agents.storage.ledger_store import get_experiment
    _make_exp(
        tmp_path, "exp_no_metrics",
        **{
            "strategy_comparison.csv": (
                "Strategy,Sharpe,MDD,CAGR,Vol,Calmar\n"
                "StratA,0.9,-0.4,0.1,0.2,0.25\n"
                "StratB,1.5,-0.3,0.2,0.18,0.66\n"
            )
        },
    )
    ingest_one(tmp_path / "exp_no_metrics", db_path=tmp_db)
    row = get_experiment("exp_no_metrics", db_path=tmp_db)
    assert row is not None
    assert abs(row["sharpe"] - 1.5) < 1e-6


def test_ingest_one_empty_folder_is_skipped(tmp_path, tmp_db):
    d = tmp_path / "exp_empty"
    d.mkdir()
    result = ingest_one(d, db_path=tmp_db)
    assert result.status == "skipped"
    assert result.variants_written == 0


def test_ingest_one_is_idempotent(tmp_path, tmp_db):
    d = _make_exp(
        tmp_path, "exp_idempotent",
        **{"metrics.json": json.dumps({"sharpe": 1.1}),
           "strategy_comparison.csv": "Strategy,Sharpe\nS1,1.1\n"},
    )
    ingest_one(d, db_path=tmp_db)
    ingest_one(d, db_path=tmp_db)  # second run
    variants = get_variants_for_experiment("exp_idempotent", db_path=tmp_db)
    assert len(variants) == 1  # no duplicate


def test_ingest_one_partial_bundle_still_ingested(tmp_path, tmp_db):
    """An experiment with only a malformed metrics.json but a valid summary is ingested."""
    d = _make_exp(
        tmp_path, "exp_partial",
        **{
            "metrics.json": "{bad json}",
            "results_summary.md": "Some notes here.",
        },
    )
    result = ingest_one(d, db_path=tmp_db)
    # summary text alone is enough to be non-empty
    assert result.status == "ingested"
    assert result.bundle_warnings  # malformed JSON logged as warning


def test_ingest_one_model_pulled_from_config(tmp_path, tmp_db):
    from agents.storage.ledger_store import get_experiment
    _make_exp(
        tmp_path, "exp_model_config",
        **{
            "config.json": json.dumps({"final_model": "smooth_drawdown_v2"}),
            "results_summary.md": "summary",
        },
    )
    ingest_one(tmp_path / "exp_model_config", db_path=tmp_db)
    row = get_experiment("exp_model_config", db_path=tmp_db)
    assert row["model"] == "smooth_drawdown_v2"


# ---------------------------------------------------------------------------
# ingest_all_completed
# ---------------------------------------------------------------------------

def test_ingest_all_completed(tmp_path, tmp_db):
    root = tmp_path / "completed"
    root.mkdir()
    _make_exp(root, "exp_a", **{"metrics.json": json.dumps({"sharpe": 1.0})})
    _make_exp(root, "exp_b", **{"metrics.json": json.dumps({"sharpe": 1.2})})
    (root / "exp_c").mkdir()  # empty — skipped

    report = ingest_all_completed(completed_dir=root, db_path=tmp_db)
    assert report.ingested == 2
    assert report.skipped == 1
    assert report.failed == 0


def test_ingest_all_skips_archive_subfolder(tmp_path, tmp_db):
    root = tmp_path / "completed"
    root.mkdir()
    archive = root / "archive"
    archive.mkdir()
    _make_exp(archive, "exp_old", **{"metrics.json": json.dumps({"sharpe": 0.5})})
    _make_exp(root, "exp_real", **{"metrics.json": json.dumps({"sharpe": 1.3})})

    report = ingest_all_completed(completed_dir=root, db_path=tmp_db)
    assert report.ingested == 1  # only exp_real, not exp_old inside archive


def test_ingest_all_missing_completed_dir_returns_empty_report(tmp_path, tmp_db):
    report = ingest_all_completed(
        completed_dir=tmp_path / "does_not_exist",
        db_path=tmp_db,
    )
    assert report.ingested == 0
    assert report.skipped == 0


def test_ingest_report_str(tmp_path, tmp_db):
    root = tmp_path / "completed"
    root.mkdir()
    _make_exp(root, "exp_x", **{"metrics.json": json.dumps({"sharpe": 1.1})})
    report = ingest_all_completed(completed_dir=root, db_path=tmp_db)
    text = str(report)
    assert "ingested" in text
    assert "exp_x" in text


# ---------------------------------------------------------------------------
# Strategy variants
# ---------------------------------------------------------------------------

def test_variants_stored_and_retrievable(tmp_path, tmp_db):
    d = _make_exp(
        tmp_path, "exp_variants",
        **{
            "strategy_comparison.csv": (
                "Strategy,Sharpe,MDD,CAGR,Vol,Calmar\n"
                "Alpha,1.5,-0.3,0.2,0.15,0.66\n"
                "Beta,0.9,-0.5,0.1,0.2,0.2\n"
            )
        },
    )
    ingest_one(d, db_path=tmp_db)
    variants = get_variants_for_experiment("exp_variants", db_path=tmp_db)
    assert len(variants) == 2
    names = [v["strategy_name"] for v in variants]
    assert "Alpha" in names and "Beta" in names


def test_variants_not_promoted_by_default(tmp_path, tmp_db):
    d = _make_exp(
        tmp_path, "exp_unpromoted",
        **{"strategy_comparison.csv": "Strategy,Sharpe\nS1,1.2\n"},
    )
    ingest_one(d, db_path=tmp_db)
    unpromoted = get_unpromoted_variants(db_path=tmp_db)
    assert any(v["strategy_name"] == "S1" for v in unpromoted)


def test_mark_variant_promoted(tmp_path, tmp_db):
    d = _make_exp(
        tmp_path, "exp_promote",
        **{"strategy_comparison.csv": "Strategy,Sharpe\nS_Promote,1.4\n"},
    )
    ingest_one(d, db_path=tmp_db)
    mark_variant_promoted("exp_promote", "S_Promote", db_path=tmp_db)
    unpromoted = get_unpromoted_variants(db_path=tmp_db)
    assert not any(v["strategy_name"] == "S_Promote" for v in unpromoted)


# ---------------------------------------------------------------------------
# Experiment type and raw_metrics
# ---------------------------------------------------------------------------

def test_experiment_type_stored_for_classification(tmp_path, tmp_db):
    from agents.storage.ledger_store import get_experiment
    import json as _json
    _make_exp(
        tmp_path, "exp_clf",
        **{"metrics.json": _json.dumps({"auc": 0.54, "accuracy": 0.59, "precision": 0.58})},
    )
    ingest_one(tmp_path / "exp_clf", db_path=tmp_db)
    row = get_experiment("exp_clf", db_path=tmp_db)
    assert row["experiment_type"] == "classification"


def test_classification_sharpe_is_null(tmp_path, tmp_db):
    """Classification experiments must not force auc into the sharpe column."""
    from agents.storage.ledger_store import get_experiment
    import json as _json
    _make_exp(
        tmp_path, "exp_clf_null",
        **{"metrics.json": _json.dumps({"auc": 0.54, "accuracy": 0.59})},
    )
    ingest_one(tmp_path / "exp_clf_null", db_path=tmp_db)
    row = get_experiment("exp_clf_null", db_path=tmp_db)
    assert row["sharpe"] is None


def test_classification_raw_metrics_stored(tmp_path, tmp_db):
    """Raw metrics JSON is stored even for non-portfolio types."""
    from agents.storage.ledger_store import get_experiment
    import json as _json
    payload = {"auc": 0.54, "accuracy": 0.59, "recall": 0.99}
    _make_exp(
        tmp_path, "exp_clf_raw",
        **{"metrics.json": _json.dumps(payload)},
    )
    ingest_one(tmp_path / "exp_clf_raw", db_path=tmp_db)
    row = get_experiment("exp_clf_raw", db_path=tmp_db)
    assert row["raw_metrics"] is not None
    stored = _json.loads(row["raw_metrics"])
    assert stored["auc"] == pytest.approx(0.54)
    assert stored["recall"] == pytest.approx(0.99)


def test_portfolio_raw_metrics_also_stored(tmp_path, tmp_db):
    from agents.storage.ledger_store import get_experiment
    import json as _json
    _make_exp(
        tmp_path, "exp_port_raw",
        **{"metrics.json": _json.dumps({"sharpe": 1.4, "mdd": -0.25})},
    )
    ingest_one(tmp_path / "exp_port_raw", db_path=tmp_db)
    row = get_experiment("exp_port_raw", db_path=tmp_db)
    assert row["raw_metrics"] is not None
    stored = _json.loads(row["raw_metrics"])
    assert stored["sharpe"] == pytest.approx(1.4)


def test_risk_overlay_type_stored(tmp_path, tmp_db):
    from agents.storage.ledger_store import get_experiment
    import json as _json
    _make_exp(
        tmp_path, "exp_risk",
        **{
            "metrics.json": _json.dumps({"sharpe": 2.09, "calmar": 1.03, "avg_exposure": 0.8}),
            "config.json": _json.dumps({"final_model": "smooth_drawdown_exposure"}),
        },
    )
    ingest_one(tmp_path / "exp_risk", db_path=tmp_db)
    row = get_experiment("exp_risk", db_path=tmp_db)
    assert row["experiment_type"] == "risk_overlay"
    # risk_overlay does map sharpe/calmar into named columns
    assert row["sharpe"] == pytest.approx(2.09)
    assert row["calmar"] == pytest.approx(1.03)


def test_extra_csv_columns_stored_in_extra_metrics(tmp_path, tmp_db):
    d = _make_exp(
        tmp_path, "exp_extra_cols",
        **{
            "strategy_comparison.csv": (
                "Strategy,Sharpe,MDD,Avg_Exposure\n"
                "S1,1.5,-0.3,0.75\n"
            )
        },
    )
    ingest_one(d, db_path=tmp_db)
    variants = get_variants_for_experiment("exp_extra_cols", db_path=tmp_db)
    assert len(variants) == 1
    # Avg_Exposure is a known column mapped directly
    assert variants[0]["avg_exposure"] == 0.75
