"""
Milestone 11 PR-1 — evidence capture and provenance.

Proves the durable evidence layer captures reliable, auditable evidence from
finished experiments and makes no promotion/retirement/confidence/deployment
decision. The 10 required proofs map 1:1 onto the tests below.
"""

from __future__ import annotations

import json

import pytest

from agents.storage.db import create_all_tables, get_connection, SCHEMA_VERSION
from agents.storage import evidence_store, ledger_store
from agents.storage.context_store import record_regime_label
from agents.storage.hypothesis_store import insert_node
from agents.research_intelligence import EvidenceRecorder


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _fresh_db(tmp_path):
    db = tmp_path / "evidence.db"
    create_all_tables(db)
    return db


def _make_experiment(db, experiment_id="EXP-1", **overrides):
    record = {
        "experiment_id": experiment_id,
        "project": "P11",
        "date": "2026-01-15",
        "hypothesis": "momentum works in low vol",
        "market": "India",
        "universe": "NIFTY50",
        "bar_type": "time",
        "features": json.dumps(["mom_12_1", "vol_20"]),
        "model": "xgb",
        "experiment_type": "portfolio",
        "sharpe": 1.4,
        "net_sharpe": 1.1,
        "net_calmar": 0.8,
        "turnover_annualized": 3.2,
        "robustness_flags": json.dumps(["passes_subsample"]),
        "source_idea_id": "IDEA-9",
        "source_model": "claude",
        "raw_metrics": json.dumps({"auc": 0.55, "capacity_usd": 5_000_000}),
        "decision": "keep",
        "status": "completed",
    }
    record.update(overrides)
    ledger_store.upsert_experiment(record, db_path=db)
    return experiment_id


# ---------------------------------------------------------------------------
# 1. One completed experiment creates one evidence event.
# ---------------------------------------------------------------------------

def test_one_experiment_creates_one_evidence_event(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)
    rec = EvidenceRecorder(db_path=db)

    new_id = rec.record("EXP-1")

    assert new_id is not None
    assert evidence_store.count(db_path=db) == 1
    rows = evidence_store.evidence_for_experiment("EXP-1", db_path=db)
    assert len(rows) == 1
    assert rows[0]["evidence_source"] == evidence_store.SOURCE_IN_SAMPLE


# ---------------------------------------------------------------------------
# 2. Reprocessing the same experiment does not create duplicate evidence.
# ---------------------------------------------------------------------------

def test_reprocessing_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)
    rec = EvidenceRecorder(db_path=db)

    first = rec.record("EXP-1")
    second = rec.record("EXP-1")          # same (experiment, source)
    third = rec.record("EXP-1")

    assert first is not None
    assert second is None                 # conflict → no duplicate written
    assert third is None
    assert evidence_store.count(db_path=db) == 1


# ---------------------------------------------------------------------------
# 3. Provenance fields survive restart and reconstruction.
# ---------------------------------------------------------------------------

def test_provenance_survives_restart(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)
    EvidenceRecorder(db_path=db).record(
        "EXP-1", dataset_id="ds-abc123", date_start="2020-01-01",
        date_end="2024-12-31",
    )
    # Simulate a process restart: brand-new connections, no in-memory state.
    row = evidence_store.evidence_for_experiment("EXP-1", db_path=db)[0]

    assert row["experiment_id"] == "EXP-1"
    assert row["campaign_id"] is None or isinstance(row["campaign_id"], str)
    assert row["source_idea_id"] == "IDEA-9"
    assert row["source_model"] == "claude"
    assert row["market"] == "India"
    assert row["universe"] == "NIFTY50"
    assert row["bar_type"] == "time"
    assert row["feature_names"] == ["mom_12_1", "vol_20"]
    assert row["dataset_id"] == "ds-abc123"
    assert row["date_start"] == "2020-01-01"
    assert row["date_end"] == "2024-12-31"
    assert row["methodology_version"] == "m11-0"
    assert row["robustness_flags"] == ["passes_subsample"]
    assert row["metrics"]["net_sharpe"] == 1.1
    assert row["metrics"]["auc"] == 0.55
    assert row["capacity_metrics"] == {"capacity_usd": 5_000_000}
    assert row["critic_decision"] == "keep"


def test_regime_and_hypothesis_link_captured(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)
    record_regime_label("EXP-1", "low_vol", db_path=db)
    insert_node(
        {
            "node_id": "NODE-1", "campaign_id": "CAMP-7", "parent_id": None,
            "root_id": "NODE-1", "depth": 0, "hypothesis": "h",
            "experiment_id": "EXP-1",
        },
        db_path=db,
    )
    EvidenceRecorder(db_path=db).record("EXP-1")
    row = evidence_store.evidence_for_experiment("EXP-1", db_path=db)[0]
    assert row["regime"] == "low_vol"
    assert row["hypothesis_id"] == "NODE-1"
    assert row["campaign_id"] == "CAMP-7"


# ---------------------------------------------------------------------------
# 4. Different evidence sources remain distinguishable.
# ---------------------------------------------------------------------------

def test_evidence_sources_are_distinguishable(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)
    rec = EvidenceRecorder(db_path=db)

    rec.record("EXP-1", evidence_source=evidence_store.SOURCE_IN_SAMPLE)
    rec.record("EXP-1", evidence_source=evidence_store.SOURCE_HOLDOUT)
    rec.record("EXP-1", evidence_source=evidence_store.SOURCE_WALK_FORWARD)
    # Re-recording holdout is still idempotent within its own source.
    assert rec.record("EXP-1", evidence_source=evidence_store.SOURCE_HOLDOUT) is None

    sources = evidence_store.evidence_sources_for("EXP-1", db_path=db)
    assert sources == {"in_sample", "holdout", "walk_forward"}
    assert evidence_store.count(db_path=db) == 3


def test_unknown_evidence_source_rejected(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)
    with pytest.raises(ValueError):
        EvidenceRecorder(db_path=db).record("EXP-1", evidence_source="bogus")


# ---------------------------------------------------------------------------
# 5. Legacy experiments can be represented without corrupting existing data.
# ---------------------------------------------------------------------------

def test_legacy_experiment_minimal_fields(tmp_path):
    db = _fresh_db(tmp_path)
    # A minimal, pre-M11 experiment: no features, no raw_metrics, no provenance.
    ledger_store.upsert_experiment(
        {"experiment_id": "LEG-1", "status": "completed"}, db_path=db
    )
    new_id = EvidenceRecorder(db_path=db).record("LEG-1")

    assert new_id is not None
    row = evidence_store.get_evidence(new_id, db_path=db)
    assert row["experiment_id"] == "LEG-1"
    assert row["feature_names"] is None
    assert row["capacity_metrics"] is None
    assert row["bar_type"] == "time"          # default, uncorrupted
    # The experiment row itself is untouched.
    exp = ledger_store.get_experiment("LEG-1", db_path=db)
    assert exp["status"] == "completed"


def test_missing_experiment_raises(tmp_path):
    db = _fresh_db(tmp_path)
    with pytest.raises(KeyError):
        EvidenceRecorder(db_path=db).record("does-not-exist")


# ---------------------------------------------------------------------------
# 6. M7 execution remains unchanged (capture never mutates experiments).
# ---------------------------------------------------------------------------

def test_m7_experiment_row_unchanged(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)
    before = ledger_store.get_experiment("EXP-1", db_path=db)
    EvidenceRecorder(db_path=db).record("EXP-1")
    after = ledger_store.get_experiment("EXP-1", db_path=db)
    assert before == after


# ---------------------------------------------------------------------------
# 7. M9 learning remains unchanged (no signal tables written by capture).
# ---------------------------------------------------------------------------

def test_m9_signal_tables_unchanged(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)

    def _counts():
        with get_connection(db) as conn:
            return (
                conn.execute("SELECT COUNT(*) c FROM signal_context_observation").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM signal_context_performance").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM signal_lifecycle_events").fetchone()["c"],
            )

    before = _counts()
    EvidenceRecorder(db_path=db).record("EXP-1")
    assert _counts() == before


# ---------------------------------------------------------------------------
# 8. M10 research-loop behaviour remains unchanged (no M10 tables written).
# ---------------------------------------------------------------------------

def test_m10_tables_unchanged(tmp_path):
    db = _fresh_db(tmp_path)
    _make_experiment(db)
    insert_node(
        {"node_id": "NODE-1", "campaign_id": "CAMP-7", "parent_id": None,
         "root_id": "NODE-1", "depth": 0, "hypothesis": "h",
         "experiment_id": "EXP-1"},
        db_path=db,
    )

    def _counts():
        with get_connection(db) as conn:
            return (
                conn.execute("SELECT COUNT(*) c FROM hypothesis_node").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM hypothesis_edge").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM scheduler_event").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM loop_checkpoint").fetchone()["c"],
                conn.execute("SELECT COUNT(*) c FROM research_campaign").fetchone()["c"],
            )

    before = _counts()
    EvidenceRecorder(db_path=db).record("EXP-1")
    after = _counts()
    assert after == before
    # The hypothesis node is read, never mutated.
    with get_connection(db) as conn:
        node = conn.execute(
            "SELECT experiment_id FROM hypothesis_node WHERE node_id='NODE-1'"
        ).fetchone()
    assert node["experiment_id"] == "EXP-1"


# ---------------------------------------------------------------------------
# 9. Schema migration: new table present, version bumped, no decision columns.
# ---------------------------------------------------------------------------

def test_schema_has_evidence_event_table(tmp_path):
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(evidence_event)")}
    # Required provenance/result fields are all present.
    for c in ("experiment_id", "hypothesis_id", "campaign_id", "source_idea_id",
              "source_model", "market", "universe", "regime", "bar_type",
              "feature_names", "dataset_id", "date_start", "date_end",
              "evidence_source", "methodology_version", "stat_method_version",
              "metrics", "robustness_flags", "capacity_metrics", "created_at"):
        assert c in cols
    # PR-1 stores evidence only: no promotion/confidence/decision columns.
    for forbidden in ("posterior_mean", "confidence", "ci_low", "stage",
                      "promotion", "retirement", "budget_alloc"):
        assert forbidden not in cols


def test_legacy_db_gains_evidence_event_table(tmp_path):
    """A pre-M11 DB without evidence_event gains it on create_all_tables()."""
    import sqlite3
    db = tmp_path / "legacy.db"
    create_all_tables(db)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE evidence_event")
        conn.commit()
    # Re-running create_all_tables reconciles the missing table.
    create_all_tables(db)
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='evidence_event'"
        ).fetchone()
    assert row is not None


# ---------------------------------------------------------------------------
# 10. A clean checkout and fresh database reproduce the same evidence rows.
# ---------------------------------------------------------------------------

def test_deterministic_reproduction_across_fresh_dbs(tmp_path):
    def _capture(dirname):
        db = tmp_path / dirname / "evidence.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        create_all_tables(db)
        _make_experiment(db)
        record_regime_label("EXP-1", "low_vol", db_path=db)
        EvidenceRecorder(db_path=db).record(
            "EXP-1", dataset_id="ds-1", date_start="2020-01-01",
            date_end="2024-12-31",
        )
        row = evidence_store.evidence_for_experiment("EXP-1", db_path=db)[0]
        # Drop volatile fields (autoincrement id, wall-clock timestamp).
        row.pop("id")
        row.pop("created_at")
        return row

    assert _capture("run_a") == _capture("run_b")
