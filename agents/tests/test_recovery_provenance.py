"""
Immutable origin provenance for recovered hypotheses.

Verifies every recovered hypothesis carries a complete, immutable origin-provenance
chain that survives replay, pause/resume, campaign recovery (rebuild-from-events), and
portfolio planning; that imported Project 02 retains its external-repo source metadata;
and that provenance rides in the existing pending_ideas.metadata (no parallel storage).
"""

from __future__ import annotations

from agents.storage.db import create_all_tables
from agents.campaign_manager import CampaignManager
from agents.research_loop.sources import build_registry, SourceContext
from agents.portfolio_planner import PortfolioPlanner
from agents import recovery
from agents.recovery import templates


def _db(tmp_path, name="prov.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _source(db):
    return build_registry(SourceContext(db_path=db, strategist=None))["historical_recovery"]


def _prov_map(db, props):
    return {p.idea_id: recovery.read_idea_provenance(p.idea_id, db_path=db)
            for p in props}


def _baseline_campaign(db, cid="rec"):
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, **templates.build_template("baseline"))
    cm.activate(cid)
    return cm


# --- every recovered hypothesis has a complete provenance chain -------------

def test_every_recovered_hypothesis_has_complete_provenance(tmp_path):
    db = _db(tmp_path)
    _baseline_campaign(db)
    props = _source(db).propose("rec")
    assert props
    for p in props:
        prov = recovery.read_idea_provenance(p.idea_id, db_path=db)
        assert prov is not None
        assert recovery.is_complete(prov)
        for field in recovery.PROVENANCE_FIELDS:
            assert field in prov


# --- Project 02 retains external-repo source metadata ----------------------

def test_project_02_provenance_points_to_external_repo(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("rec02", theme="t", campaign_type="historical_recovery",
                       scope={"strategy_ids": ["p02_volatility_regime"]})
    cm.activate("rec02")
    props = _source(db).propose("rec02")
    prov = recovery.read_idea_provenance(props[0].idea_id, db_path=db)
    assert prov["origin_project"] == "project_02_volatility_regime"
    assert prov["origin_repository"].endswith("spy-risk-volatility-model")
    assert prov["origin_commit"] == "2779bb3e92f7aafb11d806000b4906bbbaa99a4e"
    assert prov["origin_branch"] == "main"
    assert prov["origin_notebook"] == "notebooks/spy_volatility_regime_model.ipynb"
    assert prov["origin_artifact"] == "artifacts/vol_regime_calibrated_oof.csv"
    assert prov["vendored_snapshot"] is True


# --- immutability across the lifecycle -------------------------------------

def test_provenance_survives_replay_reticks(tmp_path):
    db = _db(tmp_path)
    _baseline_campaign(db)
    src = _source(db)
    before = _prov_map(db, src.propose("rec"))
    src.propose("rec")                          # converges — no new ideas
    src.propose("rec")
    after = {i: recovery.read_idea_provenance(i, db_path=db) for i in before}
    assert before == after                      # unchanged (immutable)


def test_provenance_survives_pause_resume(tmp_path):
    db = _db(tmp_path)
    cm = _baseline_campaign(db)
    before = _prov_map(db, _source(db).propose("rec"))
    cm.archive("rec")                           # pause
    cm.activate("rec")                          # resume
    after = {i: recovery.read_idea_provenance(i, db_path=db) for i in before}
    assert before == after


def test_provenance_survives_campaign_rebuild(tmp_path):
    db = _db(tmp_path)
    cm = _baseline_campaign(db)
    before = _prov_map(db, _source(db).propose("rec"))
    cm.rebuild_from_events("rec")               # campaign recovery from event log
    after = {i: recovery.read_idea_provenance(i, db_path=db) for i in before}
    assert before == after                      # ideas + their metadata untouched


def test_provenance_survives_portfolio_planning(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_portfolio("P", "recovery", budget_spec={"total": 10, "a_max": 1.0})
    tmpl = templates.build_template("baseline")
    tmpl["portfolio_id"] = "P"
    cm.create_campaign("rec", **tmpl)
    cm.activate("rec")
    before = _prov_map(db, _source(db).propose("rec"))
    # planning + budget are pure reads; they must not touch provenance
    PortfolioPlanner(db_path=db).plan("P")
    PortfolioPlanner(db_path=db).allocate_budget("P")
    after = {i: recovery.read_idea_provenance(i, db_path=db) for i in before}
    assert before == after


# --- campaign-level provenance + storage reuse -----------------------------

def test_campaign_carries_manifest_version(tmp_path):
    db = _db(tmp_path)
    _baseline_campaign(db)
    from agents.storage import campaign_store
    scope = campaign_store.get_campaign("rec", db_path=db)["scope"]
    assert scope["recovery_manifest_version"] == recovery.load_manifest()["version"]


def test_provenance_uses_existing_metadata_no_new_table(tmp_path):
    """Provenance rides in pending_ideas.metadata — no parallel storage."""
    db = _db(tmp_path)
    _baseline_campaign(db)
    props = _source(db).propose("rec")
    from agents.idea_generator import approval_queue
    idea = approval_queue.get_idea(props[0].idea_id, db_path=db)
    assert "provenance" in idea["metadata"]      # in the existing metadata JSON
    assert idea["metadata"]["provenance"]["origin_project"]


def test_provenance_timestamp_is_campaign_created_at(tmp_path):
    """Deterministic: the recovery_timestamp is the campaign's own created_at, not a
    fresh wall-clock read, so replay never regenerates it."""
    db = _db(tmp_path)
    _baseline_campaign(db)
    from agents.storage import campaign_store
    created = campaign_store.get_campaign("rec", db_path=db)["created_at"]
    props = _source(db).propose("rec")
    prov = recovery.read_idea_provenance(props[0].idea_id, db_path=db)
    assert prov["recovery_timestamp"] == created
