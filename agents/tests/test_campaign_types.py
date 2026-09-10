"""
Phase 6 P6-2 — campaign_type + HypothesisSource registry.

Proves campaigns declare WHAT via ``campaign_type`` (additive, default preserves
pre-Phase-6 behaviour), the generate phase routes to the bound source, unknown
types are safe, and the additive column migrates onto legacy DBs. Reuses the
existing config→row materialisation path — no new agent, no execution change.
"""

from __future__ import annotations

import sqlite3

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import campaign_store
from agents.campaign_manager import CampaignManager
from agents.campaign_manager.manager import STATE_ACTIVE
from agents.research_loop.loop import ResearchLoop, LoopConfig
from agents.research_loop import sources as S


def _db(tmp_path, name="c.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


class _StubStrategist:
    """Records that the default source delegated to the strategist."""
    def __init__(self):
        self.calls = []

    def run_tick(self, campaign_id):
        self.calls.append(campaign_id)
        return []


class _StubSource:
    def __init__(self):
        self.calls = []

    def propose(self, campaign_id):
        self.calls.append(campaign_id)
        return []


# --- schema / storage -----------------------------------------------------

def test_default_campaign_type(tmp_path):
    db = _db(tmp_path)
    CampaignManager(db_path=db).create_campaign("C", theme="t", goal_spec={})
    assert campaign_store.get_campaign("C", db_path=db)["campaign_type"] == "strategy_evolution"


def test_explicit_campaign_type_stored(tmp_path):
    db = _db(tmp_path)
    CampaignManager(db_path=db).create_campaign(
        "C", theme="t", goal_spec={}, campaign_type="bar_type_comparison")
    assert campaign_store.get_campaign("C", db_path=db)["campaign_type"] == "bar_type_comparison"


def test_campaign_type_survives_reconcile(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("C", theme="t", goal_spec={}, campaign_type="overlay_combination")
    cm.reconcile("C")   # rebuild the projection row from the genesis event
    assert campaign_store.get_campaign("C", db_path=db)["campaign_type"] == "overlay_combination"


def test_additive_migration_onto_legacy_db(tmp_path):
    # A pre-P6-2 research_campaign row without campaign_type.
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE research_campaign ("
            " campaign_id TEXT PRIMARY KEY, theme TEXT NOT NULL,"
            " state TEXT NOT NULL DEFAULT 'DRAFT')")
        conn.execute("INSERT INTO research_campaign (campaign_id, theme) VALUES ('OLD','t')")
        conn.commit()
    create_all_tables(db)   # applies the additive migration
    with get_connection(db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(research_campaign)").fetchall()]
        row = conn.execute(
            "SELECT campaign_type FROM research_campaign WHERE campaign_id='OLD'").fetchone()
    assert "campaign_type" in cols
    assert row["campaign_type"] == "strategy_evolution"   # default backfilled


# --- registry -------------------------------------------------------------

def test_default_registry_wires_strategy_evolution(tmp_path):
    strat = _StubStrategist()
    reg = S.default_registry(strat)
    # P6-5: the registry now also carries the self-registered near-term sources,
    # but strategy_evolution remains the strategist pass-through.
    assert S.CAMPAIGN_TYPE_STRATEGY_EVOLUTION in reg
    assert isinstance(reg[S.CAMPAIGN_TYPE_STRATEGY_EVOLUTION], S.StrategistSource)
    reg[S.CAMPAIGN_TYPE_STRATEGY_EVOLUTION].propose("C")
    assert strat.calls == ["C"]        # StrategistSource delegates to run_tick


# --- generate-phase routing ----------------------------------------------

def _active(db, cid, **kw):
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, theme="t", goal_spec={}, **kw)
    cm.transition(cid, STATE_ACTIVE, reason_code="activate")
    return cm


def test_generate_default_type_uses_strategist(tmp_path):
    db = _db(tmp_path)
    _active(db, "C")                                   # default strategy_evolution
    strat = _StubStrategist()
    loop = ResearchLoop(db_path=db, strategist=strat)
    ev = loop.run_tick("C").phase("generate").evidence
    assert ev["campaign_type"] == "strategy_evolution"
    assert strat.calls == ["C"]                        # routed to the strategist


def test_generate_routes_to_registered_source(tmp_path):
    db = _db(tmp_path)
    _active(db, "C", campaign_type="bar_type_comparison")
    src = _StubSource()
    loop = ResearchLoop(db_path=db, sources={"bar_type_comparison": src})
    ev = loop.run_tick("C").phase("generate").evidence
    assert ev["campaign_type"] == "bar_type_comparison"
    assert src.calls == ["C"]                          # routed to the injected source


def test_unknown_type_generates_nothing_safely(tmp_path):
    db = _db(tmp_path)
    _active(db, "C", campaign_type="literature_review")   # no source registered
    ev = ResearchLoop(db_path=db).run_tick("C").phase("generate").evidence
    assert ev["generated"] == 0
    assert ev["skipped_reason"] == "no_source_for_type:literature_review"


def test_injected_sources_merge_over_default(tmp_path):
    # Injecting other types must not drop the default strategy_evolution binding.
    loop = ResearchLoop(db_path=_db(tmp_path), sources={"github_mining": _StubSource()})
    assert S.CAMPAIGN_TYPE_STRATEGY_EVOLUTION in loop.sources
    assert "github_mining" in loop.sources
