"""
Tests for migration.py — one-time CSV → SQLite migration.
"""

import csv
import pytest
from pathlib import Path

from agents.storage.db import create_all_tables
from agents.quant_interface.migration import (
    migrate_csv,
    is_migrated,
    list_applied_migrations,
)


def _write_registry_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "experiment_id", "project", "date", "hypothesis", "target",
        "features", "model", "validation", "primary_metric", "result_summary",
        "conclusion", "status", "next_action", "artifact_path",
    ]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


# ---------------------------------------------------------------------------
# Basic import
# ---------------------------------------------------------------------------

def test_migrate_csv_imports_rows(tmp_path, tmp_db):
    csv_path = tmp_path / "registry.csv"
    _write_registry_csv(csv_path, [
        {"experiment_id": "EXP_001", "project": "proj_a", "status": "completed"},
        {"experiment_id": "EXP_002", "project": "proj_b", "status": "active"},
    ])
    report = migrate_csv(csv_path=csv_path, db_path=tmp_db)
    assert report.rows_imported == 2
    assert report.error is None
    assert not report.already_applied


def test_migrate_csv_rows_land_in_db(tmp_path, tmp_db):
    from agents.storage.ledger_store import get_experiment
    csv_path = tmp_path / "registry.csv"
    _write_registry_csv(csv_path, [
        {"experiment_id": "EXP_MIGRATE_001", "project": "test", "hypothesis": "Test hypothesis"},
    ])
    migrate_csv(csv_path=csv_path, db_path=tmp_db)
    row = get_experiment("EXP_MIGRATE_001", db_path=tmp_db)
    assert row is not None
    assert row["project"] == "test"


# ---------------------------------------------------------------------------
# Idempotency guard
# ---------------------------------------------------------------------------

def test_migrate_csv_does_not_rerun_by_default(tmp_path, tmp_db):
    csv_path = tmp_path / "registry.csv"
    _write_registry_csv(csv_path, [{"experiment_id": "EXP_001"}])
    migrate_csv(csv_path=csv_path, db_path=tmp_db)
    report2 = migrate_csv(csv_path=csv_path, db_path=tmp_db)
    assert report2.already_applied is True
    assert report2.rows_imported == 0


def test_migrate_csv_force_reruns(tmp_path, tmp_db):
    csv_path = tmp_path / "registry.csv"
    _write_registry_csv(csv_path, [{"experiment_id": "EXP_001"}])
    migrate_csv(csv_path=csv_path, db_path=tmp_db)
    report2 = migrate_csv(csv_path=csv_path, db_path=tmp_db, force=True)
    assert not report2.already_applied
    assert report2.rows_imported == 1


# ---------------------------------------------------------------------------
# Missing CSV
# ---------------------------------------------------------------------------

def test_migrate_csv_missing_file_returns_skipped(tmp_path, tmp_db):
    report = migrate_csv(csv_path=tmp_path / "nonexistent.csv", db_path=tmp_db)
    assert report.skipped is True
    assert report.rows_imported == 0
    assert report.error is None


# ---------------------------------------------------------------------------
# is_migrated
# ---------------------------------------------------------------------------

def test_is_migrated_false_before_run(tmp_db):
    assert is_migrated(db_path=tmp_db) is False


def test_is_migrated_true_after_run(tmp_path, tmp_db):
    csv_path = tmp_path / "registry.csv"
    _write_registry_csv(csv_path, [{"experiment_id": "EXP_X"}])
    migrate_csv(csv_path=csv_path, db_path=tmp_db)
    assert is_migrated(db_path=tmp_db) is True


# ---------------------------------------------------------------------------
# list_applied_migrations
# ---------------------------------------------------------------------------

def test_list_applied_migrations_empty_before_run(tmp_db):
    assert list_applied_migrations(db_path=tmp_db) == []


def test_list_applied_migrations_after_run(tmp_path, tmp_db):
    csv_path = tmp_path / "registry.csv"
    _write_registry_csv(csv_path, [{"experiment_id": "EXP_Y"}])
    migrate_csv(csv_path=csv_path, db_path=tmp_db)
    migrations = list_applied_migrations(db_path=tmp_db)
    assert len(migrations) == 1
    assert migrations[0]["name"] == "registry_csv_initial_import"
    assert "applied_at" in migrations[0]


# ---------------------------------------------------------------------------
# Report str
# ---------------------------------------------------------------------------

def test_report_str_on_success(tmp_path, tmp_db):
    csv_path = tmp_path / "registry.csv"
    _write_registry_csv(csv_path, [{"experiment_id": "EXP_Z"}])
    report = migrate_csv(csv_path=csv_path, db_path=tmp_db)
    assert "imported 1 rows" in str(report)


def test_report_str_on_already_applied(tmp_path, tmp_db):
    csv_path = tmp_path / "registry.csv"
    _write_registry_csv(csv_path, [{"experiment_id": "EXP_Z"}])
    migrate_csv(csv_path=csv_path, db_path=tmp_db)
    report = migrate_csv(csv_path=csv_path, db_path=tmp_db)
    assert "already applied" in str(report)


def test_report_str_on_missing_csv(tmp_path, tmp_db):
    report = migrate_csv(csv_path=tmp_path / "missing.csv", db_path=tmp_db)
    assert "CSV not found" in str(report)
