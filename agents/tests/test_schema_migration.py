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


# --- M7 (schema v6): provenance columns + pending_ideas lifecycle columns ---

def test_experiments_have_provenance_columns(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "experiments")
    assert "source_idea_id" in cols
    assert "source_model" in cols


def test_pending_ideas_have_m7_columns(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "pending_ideas")
    for c in ("market", "universe", "experiment_id"):
        assert c in cols


def test_legacy_pending_ideas_gains_market_universe_with_default(tmp_path):
    """A pre-M7 pending_ideas table gains NOT NULL market/universe defaulted
    to 'unknown', preserving existing rows."""
    db = tmp_path / "legacy_m6.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE pending_ideas ("
            " idea_id TEXT PRIMARY KEY, hypothesis TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO pending_ideas (idea_id, hypothesis, status) "
            "VALUES ('idea_001', 'legacy idea', 'pending')"
        )
        conn.commit()

    with get_connection(db) as conn:
        apply_additive_migrations(conn)
        conn.commit()

    cols = _columns(db, "pending_ideas")
    for c in ("market", "universe", "experiment_id"):
        assert c in cols

    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT * FROM pending_ideas WHERE idea_id='idea_001'"
        ).fetchone()
    assert row["hypothesis"] == "legacy idea"
    assert row["market"] == "unknown"
    assert row["universe"] == "unknown"
    assert row["experiment_id"] is None


# --- M9 (schema v7): context-aware signal intelligence tables/columns ---

M9_TABLES = (
    "signal_context_observation",
    "signal_context_performance",
    "signal_lifecycle_events",
    "regime_label",
    "research_memory",
)


def test_m9_tables_created(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in M9_TABLES:
        assert t in tables


def test_signal_library_gains_lifecycle_columns(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "signal_library")
    for c in ("lifecycle_state", "generalization_class", "promoted_at",
              "retired_at", "last_evaluated_at"):
        assert c in cols


def test_legacy_signal_library_gains_lifecycle_default(tmp_path):
    """A pre-M9 signal_library gains NOT NULL lifecycle_state defaulted to
    'observed', preserving existing rows."""
    db = tmp_path / "legacy_m8.db"
    create_all_tables(db)
    # Emulate a pre-M9 row that predates the lifecycle columns by inserting via
    # the real table (columns exist) but asserting the default applies on a row
    # written before migration in a stripped table.
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE signal_library")
        conn.execute(
            "CREATE TABLE signal_library ("
            " feature_name TEXT PRIMARY KEY, signal_type TEXT, market TEXT,"
            " universe TEXT)")
        conn.execute(
            "INSERT INTO signal_library (feature_name, signal_type) "
            "VALUES ('mom20', 'momentum')")
        conn.commit()

    with get_connection(db) as conn:
        apply_additive_migrations(conn)
        conn.commit()

    cols = _columns(db, "signal_library")
    assert "lifecycle_state" in cols
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT * FROM signal_library WHERE feature_name='mom20'").fetchone()
    assert row["lifecycle_state"] == "observed"
    assert row["generalization_class"] is None


# --- M10 (schema v8): research-campaign layer tables/columns ---

M10_TABLES = (
    "research_campaign",
    "campaign_state_events",
)


def test_m10_tables_created(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in M10_TABLES:
        assert t in tables


def test_pending_ideas_gains_campaign_id(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "pending_ideas")
    assert "campaign_id" in cols


def test_legacy_pending_ideas_gains_campaign_id(tmp_path):
    """A pre-M10 pending_ideas table gains a nullable campaign_id column,
    preserving existing rows."""
    db = tmp_path / "legacy_m9.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE pending_ideas ("
            " idea_id TEXT PRIMARY KEY, hypothesis TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO pending_ideas (idea_id, hypothesis, status) "
            "VALUES ('idea_010', 'legacy idea', 'pending')"
        )
        conn.commit()

    with get_connection(db) as conn:
        apply_additive_migrations(conn)
        conn.commit()

    cols = _columns(db, "pending_ideas")
    assert "campaign_id" in cols
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT * FROM pending_ideas WHERE idea_id='idea_010'").fetchone()
    assert row["campaign_id"] is None


def test_schema_version_includes_campaign_layer(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    # campaign layer arrived at v8; never regress below it.
    assert get_schema_version(db) >= 8


# --- M10 PR-2 (schema v9): hypothesis evolution tree ---

M10_PR2_TABLES = (
    "hypothesis_node",
    "hypothesis_edge",
)


def test_m10_pr2_tables_created(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in M10_PR2_TABLES:
        assert t in tables


def test_schema_version_includes_bar_type_layer(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    # PR-4 bumped the schema to v10 (first-class bar_type). Use >= so future
    # additive bumps do not require editing this guard.
    assert get_schema_version(db) >= 10


def test_hypothesis_node_has_audit_columns(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "hypothesis_node")
    for c in ("node_id", "campaign_id", "parent_id", "root_id", "depth",
              "hypothesis", "signals", "origin_operator", "created_at"):
        assert c in cols


def test_hypothesis_edge_has_operator_column(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "hypothesis_edge")
    for c in ("parent_id", "child_id", "operator"):
        assert c in cols


# --- M10 PR-6 (schema v11): scheduler_event log ---

def test_scheduler_event_table_created(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "scheduler_event" in tables


def test_scheduler_event_has_audit_columns(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    cols = _columns(db, "scheduler_event")
    for c in ("id", "idea_id", "campaign_id", "experiment_id", "action",
              "attempt", "reason", "evidence", "created_at"):
        assert c in cols


def test_schema_version_includes_scheduler_layer(tmp_path):
    db = tmp_path / "a.db"
    create_all_tables(db)
    # PR-6 bumped the schema to v11 (scheduler_event). Use >= so future
    # additive bumps do not require editing this guard.
    assert get_schema_version(db) >= 11


def test_legacy_db_gains_scheduler_event_table(tmp_path):
    """create_all_tables on a pre-PR-6 DB adds the scheduler_event table without
    disturbing existing data (the table uses CREATE TABLE IF NOT EXISTS)."""
    db = tmp_path / "legacy_pr5.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE pending_ideas ("
            " idea_id TEXT PRIMARY KEY, hypothesis TEXT, status TEXT)"
        )
        conn.commit()
    # Re-running full table creation is the migration path for new tables.
    create_all_tables(db)
    with get_connection(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "scheduler_event" in tables
