"""Tests for the Milestone 10 PR-3 campaign attribution layer.

These prove the five PR-3 requirements:

  1. Campaign attribution is reconstructible entirely from storage.
  2. Campaign deletion/rebuild preserves attribution integrity.
  3. Existing non-campaign experiments continue to work unchanged.
  4. Campaign-tagged observations are queryable independently of the global
     observation table.
  5. Reconstruction and lineage tests prove attribution survives rebuilds.

The attribution layer is read-only and derives everything from link keys that
already exist (``pending_ideas.campaign_id`` / ``.experiment_id`` and
``hypothesis_node.campaign_id`` / ``.idea_id``). No execution, approval, or
evaluation code is touched, so these tests build the underlying rows directly.
"""

from agents.storage import campaign_store, hypothesis_store, ledger_store
from agents.storage import campaign_attribution as attr
from agents.storage.db import get_connection
from agents.campaign_manager import CampaignManager
from agents.hypothesis_manager import HypothesisTreeManager


# ---------------------------------------------------------------------------
# Scenario builder
# ---------------------------------------------------------------------------

def _insert_idea(db, idea_id, *, campaign_id=None, experiment_id=None,
                 hypothesis="h", status="executed"):
    """Insert a pending_ideas row directly (no approval-flow involvement)."""
    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO pending_ideas (
                idea_id, hypothesis, suggested_signals, source_model,
                status, validation_ok, campaign_id, experiment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (idea_id, hypothesis, '["mom_20"]', "test-model",
             status, 1, campaign_id, experiment_id),
        )
        conn.commit()


def _insert_lesson(db, experiment_id, finding):
    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO lessons_learned (experiment_id, finding) VALUES (?, ?)",
            (experiment_id, finding),
        )
        conn.commit()


def _insert_observation(db, experiment_id, feature_name, **kw):
    cols = dict(
        experiment_id=experiment_id,
        feature_name=feature_name,
        market=kw.get("market", "India"),
        universe=kw.get("universe", "NIFTY50"),
        regime=kw.get("regime", "all"),
        bar_type=kw.get("bar_type", "time"),
    )
    keys = ", ".join(cols)
    qs = ", ".join("?" * len(cols))
    with get_connection(db) as conn:
        conn.execute(
            f"INSERT INTO signal_context_observation ({keys}) VALUES ({qs})",
            list(cols.values()),
        )
        conn.commit()


def _build_scenario(db):
    """A campaign with two executed ideas (-> two experiments, lessons, obs),
    plus an ad-hoc (non-campaign) experiment with its own idea/lesson/obs.

    Returns the campaign_id.
    """
    cid = "camp_A"
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, "alternative bars", budget_experiments=10)
    cm.activate(cid, reason_code="kickoff")

    # Hypothesis tree tagged to the campaign.
    htm = HypothesisTreeManager(db_path=db)
    root = htm.create_root(cid, "dollar bars beat time bars", node_id="n_root")
    child = htm.evolve("n_root", "vary_bar", "volume bars beat time bars",
                       node_id="n_child")

    # Two campaign-tagged, executed ideas -> two experiments.
    _insert_idea(db, "idea_1", campaign_id=cid, experiment_id="exp_c1")
    _insert_idea(db, "idea_2", campaign_id=cid, experiment_id="exp_c2")
    htm.link_idea("n_root", "idea_1")
    htm.link_experiment("n_root", "exp_c1")
    htm.link_idea("n_child", "idea_2")
    htm.link_experiment("n_child", "exp_c2")

    for eid in ("exp_c1", "exp_c2"):
        ledger_store.upsert_experiment(
            {"experiment_id": eid, "hypothesis": "h", "status": "completed"},
            db_path=db,
        )
        _insert_lesson(db, eid, f"lesson for {eid}")
        _insert_observation(db, eid, "mom_20")

    # An ad-hoc (non-campaign) experiment: idea has NO campaign_id.
    _insert_idea(db, "idea_adhoc", campaign_id=None, experiment_id="exp_adhoc")
    ledger_store.upsert_experiment(
        {"experiment_id": "exp_adhoc", "hypothesis": "h", "status": "completed"},
        db_path=db,
    )
    _insert_lesson(db, "exp_adhoc", "lesson for adhoc")
    _insert_observation(db, "exp_adhoc", "rsi_14")

    return cid


# ---------------------------------------------------------------------------
# Requirement 1 — attribution reconstructible entirely from storage
# ---------------------------------------------------------------------------

def test_forward_attribution_from_storage(tmp_db):
    cid = _build_scenario(tmp_db)

    ideas = attr.ideas_for_campaign(cid, db_path=tmp_db)
    assert {i["idea_id"] for i in ideas} == {"idea_1", "idea_2"}

    hyps = attr.hypotheses_for_campaign(cid, db_path=tmp_db)
    assert {h["node_id"] for h in hyps} == {"n_root", "n_child"}

    exp_ids = attr.experiment_ids_for_campaign(cid, db_path=tmp_db)
    assert exp_ids == ["exp_c1", "exp_c2"]

    exps = attr.experiments_for_campaign(cid, db_path=tmp_db)
    assert {e["experiment_id"] for e in exps} == {"exp_c1", "exp_c2"}

    lessons = attr.lessons_for_campaign(cid, db_path=tmp_db)
    assert {l["finding"] for l in lessons} == {
        "lesson for exp_c1", "lesson for exp_c2"}

    obs = attr.observations_for_campaign(cid, db_path=tmp_db)
    assert {o["experiment_id"] for o in obs} == {"exp_c1", "exp_c2"}


def test_attribution_summary_counts(tmp_db):
    cid = _build_scenario(tmp_db)
    summary = attr.attribution_summary(cid, db_path=tmp_db)
    assert summary == {
        "hypotheses": 2,
        "ideas": 2,
        "experiments": 2,
        "lessons": 2,
        "observations": 2,
    }


def test_link_idea_to_campaign_is_write_once(tmp_db):
    _insert_idea(tmp_db, "idea_x", campaign_id=None, experiment_id=None)
    assert campaign_store.link_idea_to_campaign("idea_x", "camp_A", db_path=tmp_db)
    # Second attempt (re-point) is refused; attribution never silently changes.
    assert not campaign_store.link_idea_to_campaign("idea_x", "camp_B", db_path=tmp_db)
    assert campaign_store.campaign_id_for_idea("idea_x", db_path=tmp_db) == "camp_A"


# ---------------------------------------------------------------------------
# Requirement 2 / 5 — deletion + rebuild preserves attribution
# ---------------------------------------------------------------------------

def test_attribution_survives_campaign_row_deletion(tmp_db):
    cid = _build_scenario(tmp_db)
    before = attr.attribution_summary(cid, db_path=tmp_db)

    # Delete only the projection row (the anchors live on ideas/hypotheses).
    campaign_store.delete_campaign_row(cid, db_path=tmp_db)
    assert campaign_store.get_campaign(cid, db_path=tmp_db) is None

    after = attr.attribution_summary(cid, db_path=tmp_db)
    assert after == before


def test_attribution_survives_rebuild_from_events(tmp_db):
    cid = _build_scenario(tmp_db)
    before = attr.attribution_summary(cid, db_path=tmp_db)
    lineage_before = attr.lineage_for_experiment("exp_c1", db_path=tmp_db)

    cm = CampaignManager(db_path=tmp_db)
    campaign_store.delete_campaign_row(cid, db_path=tmp_db)
    cm.rebuild_from_events(cid)

    assert campaign_store.get_campaign(cid, db_path=tmp_db) is not None
    assert attr.attribution_summary(cid, db_path=tmp_db) == before
    assert attr.lineage_for_experiment("exp_c1", db_path=tmp_db) == lineage_before


# ---------------------------------------------------------------------------
# Requirement 3 — non-campaign experiments unchanged
# ---------------------------------------------------------------------------

def test_non_campaign_experiment_resolves_to_no_campaign(tmp_db):
    _build_scenario(tmp_db)
    assert attr.campaign_for_experiment("exp_adhoc", db_path=tmp_db) is None
    # And it is never pulled into any campaign's artefacts.
    assert "exp_adhoc" not in attr.experiment_ids_for_campaign("camp_A", db_path=tmp_db)


def test_non_campaign_lineage_is_none_tolerant(tmp_db):
    _build_scenario(tmp_db)
    lin = attr.lineage_for_experiment("exp_adhoc", db_path=tmp_db)
    assert lin["campaign_id"] is None
    assert lin["idea"]["idea_id"] == "idea_adhoc"
    assert lin["experiment"]["experiment_id"] == "exp_adhoc"


def test_unknown_experiment_yields_empty_lineage(tmp_db):
    _build_scenario(tmp_db)
    lin = attr.lineage_for_experiment("exp_missing", db_path=tmp_db)
    assert lin == {
        "campaign_id": None,
        "idea": None,
        "hypothesis_node": None,
        "experiment": None,
    }


def test_empty_campaign_has_no_artefacts(tmp_db):
    cm = CampaignManager(db_path=tmp_db)
    cm.create_campaign("camp_empty", "nothing yet")
    assert attr.experiment_ids_for_campaign("camp_empty", db_path=tmp_db) == []
    assert attr.experiments_for_campaign("camp_empty", db_path=tmp_db) == []
    assert attr.lessons_for_campaign("camp_empty", db_path=tmp_db) == []
    assert attr.observations_for_campaign("camp_empty", db_path=tmp_db) == []


# ---------------------------------------------------------------------------
# Requirement 4 — campaign-tagged observations queryable independently
# ---------------------------------------------------------------------------

def test_campaign_observations_independent_of_global(tmp_db):
    cid = _build_scenario(tmp_db)

    # Global table holds all observations including the ad-hoc one.
    with get_connection(tmp_db) as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM signal_context_observation"
        ).fetchone()["n"]
    assert total == 3  # exp_c1, exp_c2, exp_adhoc

    # Campaign-scoped view returns only the two campaign observations and never
    # modifies or duplicates the global rows.
    camp_obs = attr.observations_for_campaign(cid, db_path=tmp_db)
    assert len(camp_obs) == 2
    assert "rsi_14" not in {o["feature_name"] for o in camp_obs}

    with get_connection(tmp_db) as conn:
        total_after = conn.execute(
            "SELECT COUNT(*) AS n FROM signal_context_observation"
        ).fetchone()["n"]
    assert total_after == total


# ---------------------------------------------------------------------------
# Reverse attribution / lineage
# ---------------------------------------------------------------------------

def test_campaign_for_experiment(tmp_db):
    cid = _build_scenario(tmp_db)
    assert attr.campaign_for_experiment("exp_c1", db_path=tmp_db) == cid
    assert attr.campaign_for_experiment("exp_c2", db_path=tmp_db) == cid


def test_lineage_chain_reconstructed_from_storage(tmp_db):
    cid = _build_scenario(tmp_db)
    lin = attr.lineage_for_experiment("exp_c1", db_path=tmp_db)
    assert lin["campaign_id"] == cid
    assert lin["idea"]["idea_id"] == "idea_1"
    assert lin["hypothesis_node"]["node_id"] == "n_root"
    assert lin["experiment"]["experiment_id"] == "exp_c1"
