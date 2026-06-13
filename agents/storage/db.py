"""
SQLite connection and schema management for the quant agent system.

Single database: agents/quant_agents.db
All tables created here via create_all_tables().
Schema versioning is handled by a simple schema_version table.
"""

from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "quant_agents.db"

SCHEMA_VERSION = 1

_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id           TEXT PRIMARY KEY,
    project                 TEXT,
    date                    TEXT,
    hypothesis              TEXT,
    target                  TEXT,
    features                TEXT,       -- JSON array
    model                   TEXT,
    market                  TEXT,
    universe                TEXT,
    validation_method       TEXT,
    expected_improvement    TEXT,
    success_criteria        TEXT,       -- JSON object
    primary_metric          TEXT,
    sharpe                  REAL,
    mdd                     REAL,
    cagr                    REAL,
    vol                     REAL,
    calmar                  REAL,
    result_summary          TEXT,
    conclusion              TEXT,
    status                  TEXT,       -- active / completed / rejected
    decision                TEXT,       -- keep / reject / retest
    next_action             TEXT,
    artifact_path           TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_SIGNAL_LIBRARY = """
CREATE TABLE IF NOT EXISTS signal_library (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_name                TEXT NOT NULL UNIQUE,
    signal_type                 TEXT,       -- momentum / mean_reversion / volatility / macro / composite
    market                      TEXT,
    universe                    TEXT,
    project_source              TEXT,
    experiment_ids              TEXT,       -- JSON array of experiment_id strings
    performance_contribution    REAL,       -- avg IC or Sharpe contribution; NULL if not yet measured
    weakness                    TEXT,
    possible_combinations       TEXT,       -- JSON array of feature_name strings
    keep_reject_retest          TEXT,       -- keep / reject / retest
    notes                       TEXT,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_LESSONS_LEARNED = """
CREATE TABLE IF NOT EXISTS lessons_learned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT NOT NULL,
    cycle_id        TEXT,
    category        TEXT,   -- signal / risk / overfitting / regime / portfolio / other
    finding         TEXT NOT NULL,
    implication     TEXT,
    confidence      TEXT,   -- high / medium / low
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
)
"""

_CREATE_AGENT_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS agent_conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id        TEXT NOT NULL,
    sender          TEXT NOT NULL,
    recipient       TEXT NOT NULL,
    message_type    TEXT NOT NULL,  -- hypothesis / spec / result / critique / lesson / summary
    payload         TEXT NOT NULL,  -- JSON blob
    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_experiments_status    ON experiments(status)",
    "CREATE INDEX IF NOT EXISTS idx_experiments_project   ON experiments(project)",
    "CREATE INDEX IF NOT EXISTS idx_signal_type           ON signal_library(signal_type)",
    "CREATE INDEX IF NOT EXISTS idx_signal_keep           ON signal_library(keep_reject_retest)",
    "CREATE INDEX IF NOT EXISTS idx_lessons_experiment    ON lessons_learned(experiment_id)",
    "CREATE INDEX IF NOT EXISTS idx_lessons_category      ON lessons_learned(category)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_cycle   ON agent_conversations(cycle_id)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_sender  ON agent_conversations(sender)",
]


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def create_all_tables(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(_CREATE_SCHEMA_VERSION)
        conn.execute(_CREATE_EXPERIMENTS)
        conn.execute(_CREATE_SIGNAL_LIBRARY)
        conn.execute(_CREATE_LESSONS_LEARNED)
        conn.execute(_CREATE_AGENT_CONVERSATIONS)
        for idx in _INDEXES:
            conn.execute(idx)
        existing = conn.execute(
            "SELECT version FROM schema_version WHERE version = ?", (SCHEMA_VERSION,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )
        conn.commit()


def get_schema_version(db_path: Path = DB_PATH) -> int | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
        return row["v"] if row else None
