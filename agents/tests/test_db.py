"""Tests for db.py — schema creation and versioning."""

import pytest
from pathlib import Path

from agents.storage.db import create_all_tables, get_schema_version, get_connection, SCHEMA_VERSION


def test_create_all_tables_idempotent(tmp_db):
    """Running create_all_tables twice must not raise."""
    create_all_tables(tmp_db)  # second call
    create_all_tables(tmp_db)  # third call — still fine


def test_schema_version_recorded(tmp_db):
    assert get_schema_version(tmp_db) == SCHEMA_VERSION


def test_all_tables_exist(tmp_db):
    expected = {"schema_version", "experiments", "signal_library", "lessons_learned", "agent_conversations"}
    with get_connection(tmp_db) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        actual = {r["name"] for r in rows}
    assert expected.issubset(actual)


def test_foreign_keys_enforced(tmp_db):
    """Inserting a lesson with a non-existent experiment_id should fail."""
    with get_connection(tmp_db) as conn:
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO lessons_learned (experiment_id, finding) VALUES (?, ?)",
                ("NONEXISTENT", "some finding"),
            )
            conn.commit()


def test_wal_mode(tmp_db):
    with get_connection(tmp_db) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
