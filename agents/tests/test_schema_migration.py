"""Tests for the additive schema migration in agents/storage/db.py."""

import sqlite3
import pytest

from agents.storage.db import (
    create_all_tables,
    get_connection,
    apply_additive_migrations,
    get_schema_version,
    SCHEMA_VERSION,
    _ADDITIVE_COLUMNS,
)

M5_COLUMNS = [c for c, _ in _ADDITIVE_COLUMNS["experiments"]]


def _columns(db_path, table):
    with get_connection(db_path) as conn:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_db_has_all_m5_columns(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "experiments")
    for c in M5_COLUMNS:
        assert c in cols


def test_schema_version_is_current(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    assert get_schema_version(db) == SCHEMA_VERSION


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    # Running again adds nothing.
    with get_connection(db) as conn:
        added = apply_additive_migrations(conn)
    assert added == []


def test_pending_ideas_table_created(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "pending_ideas")
    for c in ("idea_id", "hypothesis", "suggested_signals", "source_model",
              "metadata", "status", "validation_ok", "validation_reasons"):
        assert c in cols


def test_legacy_db_gains_pending_ideas_table(tmp_path):
    """A pre-M6 DB without pending_ideas gains it on create_all_tables()."""
    db = tmp_path / "legacy_m5.db"
    # Build the full schema, then drop pending_ideas to emulate a pre-M6 DB.
    create_all_tables(db)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE pending_ideas")
        conn.commit()
    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "pending_ideas" not in tables

    create_all_tables(db)

    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "pending_ideas" in tables
    assert get_schema_version(db) == SCHEMA_VERSION


def test_migration_upgrades_legacy_db(tmp_path):
    """A pre-M5 experiments table gains the new columns without data loss."""
    db = tmp_path / "legacy.db"
    # Create a minimal legacy experiments table missing all M5 columns.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE experiments (experiment_id TEXT PRIMARY KEY, sharpe REAL)"
        )
        conn.execute("INSERT INTO experiments (experiment_id, sharpe) VALUES ('exp_1', 1.23)")
        conn.commit()

    pre = _columns(db, "experiments")
    assert "net_sharpe" not in pre

    with get_connection(db) as conn:
        added = apply_additive_migrations(conn)
        conn.commit()

    post = _columns(db, "experiments")
    for c in M5_COLUMNS:
        assert c in post
    assert any("net_sharpe" in a for a in added)

    # Existing row preserved.
    with get_connection(db) as conn:
        row = conn.execute("SELECT * FROM experiments WHERE experiment_id='exp_1'").fetchone()
    assert row["sharpe"] == pytest.approx(1.23)
    assert row["net_sharpe"] is None
