"""
Historical Strategy Recovery — manifest, enumeration/verification, source, templates.

Proves the recovery layer is a thin, deterministic manifest reader over Projects
03-06: the manifest is structurally valid and in-scope; enumeration is verified to
cover every in-scope project (the step-4 pre-launch gate); the self-registering
HypothesisSource emits only ``pending`` ideas per campaign scope (baseline / alt-bar
sweep / blend), converges, and never runs anything; and the templates build DRAFT
campaigns via the existing CampaignManager. No research logic, no new agent, no
execution.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.campaign_manager import CampaignManager
from agents import recovery
from agents.recovery import manifest, templates
from agents.research_loop.sources import (
    build_registry, SourceContext, registered_types,
)


def _db(tmp_path, name="rec.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _pending(db, campaign_id):
    with get_connection(db) as c:
        rows = c.execute(
            "SELECT bar_type, hypothesis, status FROM pending_ideas "
            "WHERE campaign_id=? ORDER BY idea_id", (campaign_id,)).fetchall()
    return [dict(r) for r in rows]


# --- manifest integrity ----------------------------------------------------

def test_manifest_loads_and_validates():
    data = manifest.load_manifest()
    assert data["strategies"]
    ids = [s["strategy_id"] for s in data["strategies"]]
    assert len(ids) == len(set(ids))                 # unique ids


def test_manifest_only_in_scope_projects():
    for s in manifest.enumerate_strategies():
        assert s["project"] in manifest.RECOVERY_PROJECTS   # no 01/02/07


def test_manifest_no_project_01_or_07():
    # Project 01 never existed; Project 07 is the authoritative evaluator, not a source.
    # Project 02 IS now in scope (recovered/vendored) — see test_project_02_recovered.
    projects = {s["project"] for s in manifest.enumerate_strategies()}
    assert not any("project_01" in p or "project_07" in p for p in projects)


def test_project_02_recovered():
    """Project 02 is now a first-class recovered source (vendored snapshot)."""
    p02 = [s for s in manifest.enumerate_strategies()
           if s["project"] == "project_02_volatility_regime"]
    assert len(p02) == 1
    entry = p02[0]
    assert entry["status"] == "recovered_source"
    assert entry["replayable"] == "pending reproducibility verification"
    assert set(["RV5_trail", "RV20_trail", "RV5_fwd_ann", "VolRatio"]) <= set(entry["signals"])
    assert "project_02_volatility_regime" in manifest.RECOVERY_PROJECTS


def test_malformed_manifest_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"strategies": [{"strategy_id": "x"}]}')   # missing fields
    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(bad)


def test_out_of_scope_project_rejected(tmp_path):
    bad = tmp_path / "oos.json"
    bad.write_text('{"strategies": [{"strategy_id": "x", "project": "project_02_x",'
                   ' "kind": "baseline", "hypothesis": "h", "signals": ["s"],'
                   ' "market": "m", "universe": "u", "bar_type": "time"}]}')
    with pytest.raises(manifest.ManifestError):
        manifest.load_manifest(bad)


# --- enumeration verification (step 4 gate) --------------------------------

def test_verify_enumeration_covers_every_project():
    report = recovery.verify_enumeration()
    assert report["complete"] is True
    assert report["missing_projects"] == []
    for proj in manifest.RECOVERY_PROJECTS:
        assert report["coverage"][proj] >= 1          # every 03-06 represented


def test_enumeration_is_deterministic():
    a = [s["strategy_id"] for s in recovery.enumerate_strategies()]
    b = [s["strategy_id"] for s in recovery.enumerate_strategies()]
    assert a == b == sorted(a)


def test_kinds_present():
    assert recovery.strategies_for_kind(manifest.KIND_BASELINE)
    assert recovery.strategies_for_kind(manifest.KIND_BLEND)


# --- source registration + proposals ---------------------------------------

def test_recovery_source_self_registers():
    assert "historical_recovery" in registered_types()


def _source(db):
    return build_registry(SourceContext(db_path=db, strategist=None))["historical_recovery"]


def test_baseline_recovery_proposes_baselines(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("c", **templates.build_template("baseline")); cm.activate("c")
    props = _source(db).propose("c")
    assert len(props) == len(recovery.strategies_for_kind("baseline"))
    rows = _pending(db, "c")
    assert all(r["status"] == "pending" for r in rows)     # human gate intact
    assert {r["bar_type"] for r in rows} == {"time"}


def test_altbar_sweep_proposes_each_clock(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("c", **templates.build_template("altbar")); cm.activate("c")
    props = _source(db).propose("c")
    eligible = [s for s in recovery.strategies_for_kind("baseline")
                if s.get("alt_bar_eligible")]
    assert len(props) == len(eligible) * len(templates.ALT_BAR_CLOCKS)
    assert {r["bar_type"] for r in _pending(db, "c")} == set(templates.ALT_BAR_CLOCKS)


def test_blend_recovery_proposes_blends(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("c", **templates.build_template("blend")); cm.activate("c")
    props = _source(db).propose("c")
    assert len(props) == len(recovery.strategies_for_kind("blend"))


def test_recovery_source_converges(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("c", **templates.build_template("baseline")); cm.activate("c")
    src = _source(db)
    first = src.propose("c")
    assert first
    assert src.propose("c") == []                     # nothing new on re-tick


def test_explicit_strategy_ids_scope(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("c", theme="t", campaign_type="historical_recovery",
                       scope={"strategy_ids": ["p03_logistic"]})
    cm.activate("c")
    props = _source(db).propose("c")
    assert len(props) == 1


# --- templates -------------------------------------------------------------

def test_templates_build_all_kinds():
    for kind in templates.ALL_TEMPLATES:
        tmpl = templates.build_template(kind)
        assert tmpl["campaign_type"] == "historical_recovery"
        assert "scope" in tmpl


def test_unknown_template_raises():
    with pytest.raises(ValueError):
        templates.build_template("nonsense")


def test_expected_strategy_ids_matches_manifest():
    assert templates.expected_strategy_ids("baseline") == \
        [s["strategy_id"] for s in recovery.strategies_for_kind("baseline")]
    assert templates.expected_strategy_ids("blend") == \
        [s["strategy_id"] for s in recovery.strategies_for_kind("blend")]


# --- isolation -------------------------------------------------------------

def test_recovery_modules_have_no_chrysos_coupling():
    import ast
    import inspect
    for mod in (manifest, templates,
                __import__("agents.research_loop.sources.recovery",
                           fromlist=["x"])):
        tree = ast.parse(inspect.getsource(mod))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        joined = " ".join(names).lower()
        assert "chrysos" not in joined


# --- recovery connects ideas to the hypothesis-generation pipeline ----------

def test_recovery_creates_linked_hypothesis_nodes(tmp_path):
    """Recovered strategies become first-class hypothesis nodes (like the
    strategist), linked to their pending idea — closing the pending-idea ->
    hypothesis-tree connection."""
    from agents.storage import hypothesis_store
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("c", **templates.build_template("baseline")); cm.activate("c")
    props = _source(db).propose("c")
    nodes = hypothesis_store.list_nodes("c", db_path=db)
    assert len(nodes) == len(props)                    # one node per recovered idea
    for p in props:
        node = hypothesis_store.get_node_by_idea(p.idea_id, db_path=db)
        assert node is not None                        # idea linked to a node
        assert node["parent_id"] is None               # root hypothesis


def test_recovery_nodes_are_deterministic_and_converge(tmp_path):
    from agents.storage import hypothesis_store
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("c", **templates.build_template("baseline")); cm.activate("c")
    src = _source(db)
    src.propose("c")
    ids1 = sorted(n["node_id"] for n in hypothesis_store.list_nodes("c", db_path=db))
    src.propose("c")                                   # re-tick converges
    ids2 = sorted(n["node_id"] for n in hypothesis_store.list_nodes("c", db_path=db))
    assert ids1 == ids2                                # no duplicate nodes


def test_recovery_ideas_start_pending(tmp_path):
    """The experiments stay 0 until approval — the human gate is intact."""
    from agents.idea_generator import approval_queue
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("c", **templates.build_template("baseline")); cm.activate("c")
    props = _source(db).propose("c")
    pending = {i["idea_id"] for i in approval_queue.list_pending(db_path=db)}
    assert {p.idea_id for p in props} <= pending
    assert approval_queue.list_approved(db_path=db) == []
