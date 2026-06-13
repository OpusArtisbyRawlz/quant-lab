"""Tests for ledger_store.py — experiments table."""

import pytest
import csv
import tempfile
from pathlib import Path

from agents.storage import ledger_store as ls


EXP_BASE = {
    "experiment_id": "EXP_TEST_001",
    "project": "project_test",
    "date": "2026-06-11",
    "hypothesis": "Momentum beats mean-reversion in trending markets",
    "target": "5d forward return",
    "features": ["momentum_20d", "vol_20d"],
    "model": "quantile_ranking",
    "market": "US_equity",
    "universe": "sp500",
    "validation_method": "walk_forward",
    "expected_improvement": "Sharpe > 1.0",
    "success_criteria": {"sharpe": 1.0, "mdd": -0.3},
    "status": "active",
}


def test_upsert_and_get(tmp_db):
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    row = ls.get_experiment("EXP_TEST_001", db_path=tmp_db)
    assert row is not None
    assert row["hypothesis"] == EXP_BASE["hypothesis"]
    assert row["status"] == "active"


def test_upsert_is_idempotent(tmp_db):
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    rows = ls.list_experiments(db_path=tmp_db)
    assert len(rows) == 1


def test_upsert_updates_fields(tmp_db):
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    updated = EXP_BASE.copy()
    updated["status"] = "completed"
    ls.upsert_experiment(updated, db_path=tmp_db)
    row = ls.get_experiment("EXP_TEST_001", db_path=tmp_db)
    assert row["status"] == "completed"


def test_update_status(tmp_db):
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    ls.update_status("EXP_TEST_001", status="completed", decision="keep",
                     next_action="Combine with regime filter", db_path=tmp_db)
    row = ls.get_experiment("EXP_TEST_001", db_path=tmp_db)
    assert row["status"] == "completed"
    assert row["decision"] == "keep"
    assert row["next_action"] == "Combine with regime filter"


def test_update_metrics(tmp_db):
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    metrics = {"sharpe": 1.35, "mdd": -0.22, "cagr": 0.18, "vol": 0.13, "calmar": 0.82}
    ls.update_metrics("EXP_TEST_001", metrics, result_summary="Strong result", db_path=tmp_db)
    row = ls.get_experiment("EXP_TEST_001", db_path=tmp_db)
    assert abs(row["sharpe"] - 1.35) < 1e-6
    assert row["result_summary"] == "Strong result"


def test_list_experiments_filter_by_status(tmp_db):
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    exp2 = EXP_BASE.copy()
    exp2["experiment_id"] = "EXP_TEST_002"
    exp2["status"] = "completed"
    ls.upsert_experiment(exp2, db_path=tmp_db)

    active = ls.list_experiments(status="active", db_path=tmp_db)
    completed = ls.list_experiments(status="completed", db_path=tmp_db)
    assert len(active) == 1
    assert len(completed) == 1


def test_get_best_experiments(tmp_db):
    for i, sharpe in enumerate([1.5, 0.8, 1.2]):
        exp = EXP_BASE.copy()
        exp["experiment_id"] = f"EXP_TEST_{i:03d}"
        exp["status"] = "completed"
        ls.upsert_experiment(exp, db_path=tmp_db)
        ls.update_metrics(f"EXP_TEST_{i:03d}", {"sharpe": sharpe}, db_path=tmp_db)

    best = ls.get_best_experiments(metric="sharpe", top_n=2, db_path=tmp_db)
    assert best[0]["sharpe"] >= best[1]["sharpe"]
    assert len(best) == 2


def test_get_rejected_experiments(tmp_db):
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    ls.update_status("EXP_TEST_001", status="completed", decision="reject", db_path=tmp_db)
    rejected = ls.get_rejected_experiments(db_path=tmp_db)
    assert any(r["experiment_id"] == "EXP_TEST_001" for r in rejected)


def test_summary_stats(tmp_db):
    ls.upsert_experiment(EXP_BASE.copy(), db_path=tmp_db)
    stats = ls.summary_stats(db_path=tmp_db)
    assert stats["total"] == 1


def test_import_from_csv(tmp_db, tmp_path):
    csv_path = tmp_path / "registry.csv"
    fieldnames = [
        "experiment_id", "project", "date", "hypothesis", "target",
        "features", "model", "validation", "primary_metric", "result_summary",
        "conclusion", "status", "next_action", "artifact_path",
    ]
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerow({
            "experiment_id": "EXP_CSV_001",
            "project": "csv_project",
            "date": "2026-06-01",
            "hypothesis": "CSV import test",
            "target": "5d return",
            "features": "momentum",
            "model": "quantile",
            "validation": "walk_forward",
            "primary_metric": "sharpe",
            "result_summary": "pending",
            "conclusion": "",
            "status": "active",
            "next_action": "",
            "artifact_path": "experiments/active/exp_csv_001",
        })

    count = ls.import_from_csv(csv_path=csv_path, db_path=tmp_db)
    assert count == 1
    row = ls.get_experiment("EXP_CSV_001", db_path=tmp_db)
    assert row is not None
    assert row["project"] == "csv_project"


def test_get_nonexistent_experiment(tmp_db):
    assert ls.get_experiment("DOES_NOT_EXIST", db_path=tmp_db) is None
