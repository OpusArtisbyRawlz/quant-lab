"""
M11 PR-10 — GeneralisationProjector tests (generalisation_matrix projection).

Proves the projector is a pure, replay-deterministic, idempotent fold whose
per-dimension detail aggregates to the exact G-axis scalars already on
``hypothesis_state`` (no divergence), mutates no evidence, and touches no
promotion input.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import evidence_store, generalisation_store, hypothesis_state_store
from agents.research_intelligence import EvidenceProjector, GeneralisationProjector
from agents.research_intelligence.statistics import GENERALISATION_DIMENSIONS


def _fresh_db(tmp_path, name="gen.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db, hid, market, regime, n=6, s=1.6, start=0):
    for i in range(start, start + n):
        yr = 2005 + (i - start)
        evidence_store.record_evidence(
            f"{hid}-{market}-{regime}-{i}", hypothesis_id=hid, market=market,
            universe="NIFTY", regime=regime, bar_type="time",
            date_start=f"{yr}-01-01", date_end=f"{yr}-12-31",
            metrics={"net_sharpe": s, "T": 2520, "N": 252, "K": 1}, db_path=db)


def _multi_cell(db, hid="H"):
    _seed(db, hid, "IN", "low_vol", start=0)
    _seed(db, hid, "IN", "high_vol", start=100)
    _seed(db, hid, "US", "low_vol", start=200)
    _seed(db, hid, "US", "high_vol", start=300)
    _seed(db, hid, "JP", "low_vol", s=0.02, start=400)   # weak → fails


def _project(db):
    EvidenceProjector(db_path=db).rebuild_all()
    return GeneralisationProjector(db_path=db).rebuild_all()


def _no_ts(row):
    row = dict(row)
    row.pop("last_rebuilt_at", None)
    return row


# --- basic projection -----------------------------------------------------

def test_rebuild_writes_all_five_dimensions(tmp_path):
    db = _fresh_db(tmp_path)
    _multi_cell(db)
    assert _project(db) == ["H"]
    rows = generalisation_store.list_matrix("H", db_path=db)
    assert {r["dimension"] for r in rows} == set(GENERALISATION_DIMENSIONS)
    assert rows[0]["method"] == "stat_v1"


def test_matrix_aggregates_match_hypothesis_state(tmp_path):
    # The per-dimension detail must reduce to the exact G-axis scalars PR-2 stored.
    db = _fresh_db(tmp_path)
    _multi_cell(db)
    _project(db)
    st = hypothesis_state_store.get_hypothesis_state("H", db_path=db)
    for r in generalisation_store.list_matrix("H", db_path=db):
        assert r["g_count"] == st["g_count"]
        assert r["g_coverage"] == pytest.approx(st["g_coverage"])


def test_market_coverage_reflects_one_failing_market(tmp_path):
    db = _fresh_db(tmp_path)
    _multi_cell(db)
    _project(db)
    m = generalisation_store.get_dimension("H", "market", db_path=db)
    assert m["available"] == 3 and m["passing"] == 2      # IN,US pass; JP fails


# --- determinism ----------------------------------------------------------

def test_rebuild_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    _multi_cell(db)
    _project(db)
    first = [_no_ts(r) for r in generalisation_store.list_matrix("H", db_path=db)]
    GeneralisationProjector(db_path=db).rebuild_all()
    second = [_no_ts(r) for r in generalisation_store.list_matrix("H", db_path=db)]
    assert first == second
    assert len(second) == 5                               # no duplicate dim rows


def test_replay_deterministic_across_insertion_order(tmp_path):
    def build(reverse, name):
        db = _fresh_db(tmp_path, name)
        cells = [("IN", "low_vol", 1.6, 0), ("US", "high_vol", 1.6, 100),
                 ("JP", "low_vol", 0.02, 400)]
        for market, regime, s, start in (reversed(cells) if reverse else cells):
            _seed(db, "H", market, regime, s=s, start=start)
        _project(db)
        return [_no_ts(r) for r in generalisation_store.list_matrix("H", db_path=db)]

    assert build(False, "a.db") == build(True, "b.db")


def test_deterministic_rebuild_from_empty_database(tmp_path):
    db = _fresh_db(tmp_path)
    assert GeneralisationProjector(db_path=db).rebuild_all() == []
    _multi_cell(db)
    _project(db)
    before = [_no_ts(r) for r in generalisation_store.list_matrix("H", db_path=db)]
    with get_connection(db) as conn:
        conn.execute("DELETE FROM generalisation_matrix")
        conn.commit()
    GeneralisationProjector(db_path=db).rebuild_all()
    after = [_no_ts(r) for r in generalisation_store.list_matrix("H", db_path=db)]
    assert before == after


def test_prune_removes_departed_hypothesis(tmp_path):
    db = _fresh_db(tmp_path)
    _multi_cell(db, "H")
    _project(db)
    generalisation_store.replace_matrix(
        "GHOST", [{"dimension": "market", "passing": 0, "available": 0,
                   "coverage": 0.0, "g_count": 0, "g_coverage": 0.0}], db_path=db)
    GeneralisationProjector(db_path=db).rebuild_all()
    assert generalisation_store.list_matrix("GHOST", db_path=db) == []


# --- boundaries -----------------------------------------------------------

def test_evidence_events_are_never_mutated(tmp_path):
    db = _fresh_db(tmp_path)
    _multi_cell(db)
    EvidenceProjector(db_path=db).rebuild_all()

    def _snapshot():
        with get_connection(db) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT * FROM evidence_event ORDER BY id").fetchall()]

    before = _snapshot()
    GeneralisationProjector(db_path=db).rebuild_all()
    GeneralisationProjector(db_path=db).rebuild_all()
    assert _snapshot() == before


def test_does_not_touch_hypothesis_state(tmp_path):
    db = _fresh_db(tmp_path)
    _multi_cell(db)
    EvidenceProjector(db_path=db).rebuild_all()
    before = _no_ts(hypothesis_state_store.get_hypothesis_state("H", db_path=db))
    GeneralisationProjector(db_path=db).rebuild_all()
    after = _no_ts(hypothesis_state_store.get_hypothesis_state("H", db_path=db))
    assert before == after


# --- schema ---------------------------------------------------------------

def test_projection_table_exists_and_is_rebuildable(tmp_path):
    import sqlite3
    db = _fresh_db(tmp_path)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='generalisation_matrix'"
        ).fetchone() is not None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE generalisation_matrix")
        conn.commit()
    create_all_tables(db)
    with get_connection(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='generalisation_matrix'"
        ).fetchone() is not None
