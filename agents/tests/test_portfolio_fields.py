"""
Phase 6 P6-8 — extended campaign fields (portfolio-planning inputs).

Proves the additive extended-field layer: fresh + legacy schema carry the new
columns, campaigns created the old way behave exactly as before (back-compat), the
new fields round-trip (JSON decoded) and are reconstructible from the event log, and
the effective-value accessors apply the documented defaults. These are planning
INPUTS only — the scheduler/loop behaviour is unchanged by P6-8.
"""

from __future__ import annotations

import sqlite3

from agents.storage.db import (
    create_all_tables, get_connection, apply_additive_migrations,
)
from agents.storage import campaign_store as cs
from agents.campaign_manager import CampaignManager
from agents.campaign_manager.manager import STATE_ACTIVE


_EXTENDED_COLUMNS = [
    "priority", "trigger_spec", "depends_on",
    "expected_information_gain", "eig_spec", "repeat_spec", "portfolio_id",
]


def _columns(db, table):
    with get_connection(db) as conn:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _db(tmp_path, name="p.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


# --- schema ----------------------------------------------------------------

def test_fresh_db_has_extended_campaign_columns(tmp_path):
    db = _db(tmp_path)
    cols = _columns(db, "research_campaign")
    for c in _EXTENDED_COLUMNS:
        assert c in cols


def test_legacy_campaign_gains_extended_columns_with_defaults(tmp_path):
    """A pre-P6-8 research_campaign table gains the extended columns; the JSON
    columns take their spec defaults and existing rows are preserved."""
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE research_campaign ("
            " campaign_id TEXT PRIMARY KEY, theme TEXT NOT NULL,"
            " state TEXT NOT NULL DEFAULT 'DRAFT')"
        )
        conn.execute(
            "INSERT INTO research_campaign (campaign_id, theme) VALUES ('old', 't')"
        )
        conn.commit()

    with get_connection(db) as conn:
        apply_additive_migrations(conn)
        conn.commit()

    cols = _columns(db, "research_campaign")
    for c in _EXTENDED_COLUMNS:
        assert c in cols
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT * FROM research_campaign WHERE campaign_id='old'").fetchone()
    assert row["priority"] is None
    assert row["portfolio_id"] is None
    assert row["trigger_spec"] == '{"kind": "manual"}'
    assert row["depends_on"] == "[]"
    assert row["repeat_spec"] == '{"mode": "once"}'


# --- back-compat (create the old way) --------------------------------------

def test_legacy_create_is_unchanged(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("C", theme="t", goal_spec={"priority": 5})
    row = cs.get_campaign("C", db_path=db)
    # Columns are NULL when not supplied; effective accessors give the defaults.
    assert row["priority"] is None
    assert cs.campaign_priority(row) == 5.0          # falls back to goal_spec
    assert cs.campaign_trigger_spec(row) == {"kind": "manual"}
    assert cs.campaign_repeat_spec(row) == {"mode": "once"}
    assert cs.campaign_depends_on(row) == []
    assert row["portfolio_id"] is None


def test_priority_default_when_absent_everywhere(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("C", theme="t")               # no priority anywhere
    assert cs.campaign_priority(cs.get_campaign("C", db_path=db)) == 0.0


# --- extended create -------------------------------------------------------

def test_extended_fields_roundtrip(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign(
        "E", theme="t",
        priority=3.5,
        trigger_spec={"kind": "schedule", "every": 2},
        depends_on=["A", "B"],
        expected_information_gain=1.25,
        eig_spec={"signal": "evoi", "agg": "mean"},
        repeat_spec={"mode": "count", "max_repeats": 3},
        portfolio_id="P1",
    )
    row = cs.get_campaign("E", db_path=db)
    assert row["priority"] == 3.5
    assert row["trigger_spec"] == {"kind": "schedule", "every": 2}
    assert row["depends_on"] == ["A", "B"]
    assert row["expected_information_gain"] == 1.25
    assert row["eig_spec"] == {"signal": "evoi", "agg": "mean"}
    assert row["repeat_spec"] == {"mode": "count", "max_repeats": 3}
    assert row["portfolio_id"] == "P1"
    # Effective accessors honour the explicit values.
    assert cs.campaign_priority(row) == 3.5
    assert cs.campaign_depends_on(row) == ["A", "B"]


def test_extended_fields_reconstructible_from_events(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign(
        "E", theme="t", priority=2.0, portfolio_id="P9",
        trigger_spec={"kind": "dependency"}, depends_on=["A"],
    )
    # Drop the projection row and rebuild purely from the genesis event.
    cs.delete_campaign_row("E", db_path=db)
    rebuilt = cm.rebuild_from_events("E")
    assert rebuilt["priority"] == 2.0
    assert rebuilt["portfolio_id"] == "P9"
    assert rebuilt["trigger_spec"] == {"kind": "dependency"}
    assert rebuilt["depends_on"] == ["A"]


# --- scheduler behaviour unchanged -----------------------------------------

def test_scheduler_queue_unaffected_by_extended_fields(tmp_path):
    """A campaign carrying extended fields still queues exactly as a plain ACTIVE
    campaign — P6-8 only stores; it changes no scheduling behaviour."""
    from agents.research_scheduler import ResearchScheduler
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("plain", theme="t", goal_spec={"priority": 1})
    cm.activate("plain")
    cm.create_campaign("rich", theme="t", goal_spec={"priority": 2},
                       priority=9.0, portfolio_id="P1",
                       trigger_spec={"kind": "schedule"}, repeat_spec={"mode": "count"})
    cm.activate("rich")
    queue = ResearchScheduler(db, campaign_manager=cm).campaign_queue()
    ids = [c["campaign_id"] for c in queue]
    # Ordering still by goal_spec.priority (rich=2 before plain=1); the new
    # `priority` column is NOT consumed yet (that is P6-10).
    assert ids == ["rich", "plain"]
    assert cm.current_state("rich") == STATE_ACTIVE
