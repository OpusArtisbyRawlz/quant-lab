"""
Phase 6 P6-4 — Project 07 hand-off (preliminary → authoritative boundary).

Proves the neutral surface between the factory (M11 = preliminary) and Project 07
(authoritative): the DERIVED pending queue (COMPLETED minus evaluated), Project 07's
upsert write of an authoritative verdict, verdict reads, and the evaluation-status
axis. Also asserts the boundary's isolation: the store does not import Project 07 or
Chrysos, and the factory never writes the evaluation table.
"""

from __future__ import annotations

from agents.storage.db import create_all_tables
from agents.campaign_manager import CampaignManager
from agents.storage import handoff_store
from agents.storage.handoff_store import (
    STATUS_IN_PROGRESS, STATUS_PRELIMINARY, STATUS_AUTHORITATIVE,
)


def _db(tmp_path, name="h.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _completed(cm, cid):
    cm.create_campaign(cid, theme="t", goal_spec={"priority": 1})
    cm.activate(cid)
    cm.complete(cid)


# --- derived pending queue -------------------------------------------------

def test_pending_handoffs_lists_completed_unevaluated(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _completed(cm, "C1")
    _completed(cm, "C2")
    assert handoff_store.pending_handoffs(db_path=db) == ["C1", "C2"]


def test_pending_excludes_active_and_draft(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("C_draft", theme="t", goal_spec={"priority": 1})
    cm.create_campaign("C_active", theme="t", goal_spec={"priority": 1})
    cm.activate("C_active")
    _completed(cm, "C_done")
    assert handoff_store.pending_handoffs(db_path=db) == ["C_done"]


def test_pending_excludes_evaluated(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _completed(cm, "C1")
    _completed(cm, "C2")
    handoff_store.record_evaluation("C1", verdict={"pass": True}, method="p07-v1", db_path=db)
    assert handoff_store.pending_handoffs(db_path=db) == ["C2"]


def test_pending_is_deterministically_ordered(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    for cid in ("C_z", "C_a", "C_m"):
        _completed(cm, cid)
    assert handoff_store.pending_handoffs(db_path=db) == ["C_a", "C_m", "C_z"]


# --- Project 07's write + reads --------------------------------------------

def test_record_and_get_evaluation_roundtrips_verdict(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _completed(cm, "C1")
    handoff_store.record_evaluation(
        "C1", verdict={"significant": True, "p": 0.01}, method="p07-v2", db_path=db)
    ev = handoff_store.get_evaluation("C1", db_path=db)
    assert ev["campaign_id"] == "C1"
    assert ev["verdict"] == {"significant": True, "p": 0.01}
    assert ev["method"] == "p07-v2"
    assert ev["status"] == STATUS_AUTHORITATIVE


def test_get_evaluation_missing_is_none(tmp_path):
    db = _db(tmp_path)
    assert handoff_store.get_evaluation("nope", db_path=db) is None


def test_record_evaluation_is_upsert(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _completed(cm, "C1")
    handoff_store.record_evaluation("C1", verdict={"v": 1}, method="a", db_path=db)
    handoff_store.record_evaluation("C1", verdict={"v": 2}, method="b", db_path=db)
    assert len(handoff_store.list_evaluations(db_path=db)) == 1
    assert handoff_store.get_evaluation("C1", db_path=db)["verdict"] == {"v": 2}


def test_list_evaluations_ordered(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    for cid in ("C2", "C1"):
        _completed(cm, cid)
        handoff_store.record_evaluation(cid, verdict={}, db_path=db)
    ids = [e["campaign_id"] for e in handoff_store.list_evaluations(db_path=db)]
    assert ids == ["C1", "C2"]


# --- the preliminary → authoritative axis ----------------------------------

def test_status_in_progress_for_active(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_campaign("C1", theme="t", goal_spec={"priority": 1})
    cm.activate("C1")
    assert handoff_store.evaluation_status("C1", db_path=db) == STATUS_IN_PROGRESS


def test_status_preliminary_after_completion(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _completed(cm, "C1")
    assert handoff_store.evaluation_status("C1", db_path=db) == STATUS_PRELIMINARY


def test_status_authoritative_after_project07(tmp_path):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    _completed(cm, "C1")
    handoff_store.record_evaluation("C1", verdict={"ok": True}, db_path=db)
    assert handoff_store.evaluation_status("C1", db_path=db) == STATUS_AUTHORITATIVE


# --- isolation guarantees --------------------------------------------------

def test_handoff_store_does_not_import_project07_or_chrysos(tmp_path):
    import ast
    import inspect
    import agents.storage.handoff_store as mod

    tree = ast.parse(inspect.getsource(mod))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    joined = " ".join(modules).lower()
    # No dependency on the authoritative evaluator, and no Chrysos coupling.
    assert "chrysos" not in joined
    assert "project" not in joined
    assert "project07" not in joined


def test_factory_runner_never_writes_evaluation_table(tmp_path):
    import agents.research_loop.factory_runner as mod
    src = __import__("inspect").getsource(mod)
    assert "project07_evaluation" not in src
    assert "handoff_store" not in src
