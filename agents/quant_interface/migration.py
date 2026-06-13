"""
One-time migration: registry.csv → SQLite experiments table.

SQLite is the single source of truth. This module exists solely to bootstrap
the DB from the legacy CSV on first run. Once the migration is recorded in the
migrations table it will not re-run unless force=True is passed.

Usage:
    from agents.quant_interface.migration import migrate_csv

    report = migrate_csv()
    print(report)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agents.storage.db import get_connection, create_all_tables, DB_PATH
from agents.storage.ledger_store import import_from_csv, REGISTRY_CSV

log = logging.getLogger(__name__)

_MIGRATION_NAME = "registry_csv_initial_import"


@dataclass
class MigrationReport:
    name: str
    already_applied: bool = False
    rows_imported: int = 0
    skipped: bool = False
    error: str | None = None

    def __str__(self) -> str:
        if self.already_applied:
            return f"Migration '{self.name}': already applied, skipped."
        if self.error:
            return f"Migration '{self.name}': FAILED — {self.error}"
        if self.skipped:
            return f"Migration '{self.name}': CSV not found, nothing to import."
        return f"Migration '{self.name}': imported {self.rows_imported} rows."


def migrate_csv(
    csv_path: Path = REGISTRY_CSV,
    db_path: Path = DB_PATH,
    force: bool = False,
) -> MigrationReport:
    """
    Import registry.csv into the experiments table.

    Parameters
    ----------
    csv_path : Path
        Location of registry.csv (default: experiments/registry.csv).
    db_path : Path
        SQLite database to write to.
    force : bool
        If True, re-run even if already applied (upsert is safe to repeat).

    Returns
    -------
    MigrationReport
    """
    create_all_tables(db_path)
    report = MigrationReport(name=_MIGRATION_NAME)

    if not force and _is_applied(_MIGRATION_NAME, db_path):
        report.already_applied = True
        log.info("Migration '%s' already applied — pass force=True to re-run.", _MIGRATION_NAME)
        return report

    if not csv_path.exists():
        report.skipped = True
        log.warning("registry.csv not found at %s — nothing imported.", csv_path)
        return report

    try:
        rows = import_from_csv(csv_path=csv_path, db_path=db_path)
        report.rows_imported = rows
        _record_migration(
            _MIGRATION_NAME,
            notes=f"Imported {rows} rows from {csv_path}",
            db_path=db_path,
        )
        log.info("Migration '%s' complete: %d rows imported.", _MIGRATION_NAME, rows)
    except Exception as exc:
        report.error = str(exc)
        log.exception("Migration '%s' failed.", _MIGRATION_NAME)

    return report


def is_migrated(db_path: Path = DB_PATH) -> bool:
    """Return True if the initial CSV migration has been applied."""
    return _is_applied(_MIGRATION_NAME, db_path)


def list_applied_migrations(db_path: Path = DB_PATH) -> list[dict]:
    """Return all recorded migrations in application order."""
    try:
        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM migrations ORDER BY applied_at"
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _is_applied(name: str, db_path: Path) -> bool:
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT id FROM migrations WHERE name = ?", (name,)
            ).fetchone()
            return row is not None
    except Exception:
        return False


def _record_migration(name: str, notes: str, db_path: Path) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO migrations (name, applied_at, notes) VALUES (?, ?, ?)",
            (name, datetime.now(timezone.utc).isoformat(), notes),
        )
        conn.commit()
