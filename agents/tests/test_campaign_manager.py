"""Tests for the Milestone 10 CampaignManager and campaign_store."""

import pytest

from agents.storage import campaign_store
from agents.storage.campaign_store import (
    STATE_DRAFT,
    STATE_ACTIVE,
    STATE_STALLED,
    STATE_COMPLETED,
    STATE_ARCHIVED,
    STATE_DISCARDED,
)
from agents.campaign_manager import (
    CampaignManager,
    CampaignError,
    is_legal_transition,
)


# ---------------------------------------------------------------------------
# campaign_store low-level
# ---------------------------------------------------------------------------

def test_insert_and_get_campaign(tmp_db):
    campaign_store.insert_campaign(
        {
            "campaign_id": "camp_001",
            "theme": "alternative bars",
            "goal_spec": {"objective": "compare bar types"},
            "scope": {"markets": ["India"], "universes": ["NIFTY50"]},
            "budget_experiments": 10,
        },
        db_path=tmp_db,
    )
    c = campaign_store.get_campaign("camp_001", db_path=tmp_db)
    assert c is not None
    assert c["theme"] == "alternative bars"
    assert c["state"] == STATE_DRAFT
    assert c["budget_experiments"] == 10
    # JSON round-trips back to a Python object.
    assert c["goal_spec"] == {"objective": "compare bar types"}
    assert c["scope"]["markets"] == ["India"]


def test_get_missing_campaign_returns_none(tmp_db):
    assert campaign_store.get_campaign("nope", db_path=tmp_db) is None


def test_list_campaigns_filters_by_state(tmp_db):
    campaign_store.insert_campaign(
        {"campaign_id": "c1", "theme": "t1", "state": STATE_DRAFT}, db_path=tmp_db)
    campaign_store.insert_campaign(
        {"campaign_id": "c2", "theme": "t2", "state": STATE_ACTIVE}, db_path=tmp_db)
    assert len(campaign_store.list_campaigns(db_path=tmp_db)) == 2
    active = campaign_store.list_campaigns(state=STATE_ACTIVE, db_path=tmp_db)
    assert [c["campaign_id"] for c in active] == ["c2"]


def test_append_and_list_state_events(tmp_db):
    campaign_store.insert_campaign(
        {"campaign_id": "c1", "theme": "t1"}, db_path=tmp_db)
    campaign_store.append_state_event(
        "c1", from_state=None, to_state=STATE_DRAFT,
        reason_code="created", evidence={"k": "v"}, db_path=tmp_db)
    campaign_store.append_state_event(
        "c1", from_state=STATE_DRAFT, to_state=STATE_ACTIVE,
        reason_code="activated", db_path=tmp_db)
    events = campaign_store.list_state_events("c1", db_path=tmp_db)
    assert len(events) == 2
    assert events[0]["to_state"] == STATE_DRAFT
    assert events[0]["evidence"] == {"k": "v"}
    assert events[1]["to_state"] == STATE_ACTIVE


# ---------------------------------------------------------------------------
# transition legality table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frm,to,ok", [
    (STATE_DRAFT, STATE_ACTIVE, True),
    (STATE_DRAFT, STATE_DISCARDED, True),
    (STATE_DRAFT, STATE_COMPLETED, False),
    (STATE_ACTIVE, STATE_STALLED, True),
    (STATE_ACTIVE, STATE_COMPLETED, True),
    (STATE_STALLED, STATE_ACTIVE, True),
    (STATE_COMPLETED, STATE_ACTIVE, False),
    (STATE_DISCARDED, STATE_ACTIVE, False),
    (STATE_ARCHIVED, STATE_ACTIVE, True),
    (STATE_ACTIVE, STATE_ACTIVE, True),   # same-state is legal (no-op)
])
def test_is_legal_transition(frm, to, ok):
    assert is_legal_transition(frm, to) is ok


# ---------------------------------------------------------------------------
# CampaignManager
# ---------------------------------------------------------------------------

def test_create_campaign_starts_in_draft_with_event(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    c = mgr.create_campaign("camp_001", "alt bars", budget_experiments=5)
    assert c["state"] == STATE_DRAFT
    events = campaign_store.list_state_events("camp_001", db_path=tmp_db)
    assert len(events) == 1
    assert events[0]["from_state"] is None
    assert events[0]["to_state"] == STATE_DRAFT
    assert events[0]["reason_code"] == "created"


def test_create_duplicate_raises(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    with pytest.raises(CampaignError):
        mgr.create_campaign("camp_001", "t")


def test_legal_transition_updates_state_and_emits_event(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    res = mgr.activate("camp_001")
    assert res.changed is True
    assert res.from_state == STATE_DRAFT
    assert res.to_state == STATE_ACTIVE
    assert res.event_id is not None
    c = campaign_store.get_campaign("camp_001", db_path=tmp_db)
    assert c["state"] == STATE_ACTIVE
    events = campaign_store.list_state_events("camp_001", db_path=tmp_db)
    assert events[-1]["to_state"] == STATE_ACTIVE


def test_illegal_transition_raises_and_does_not_change_state(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    with pytest.raises(CampaignError):
        mgr.complete("camp_001")   # DRAFT -> COMPLETED is illegal
    c = campaign_store.get_campaign("camp_001", db_path=tmp_db)
    assert c["state"] == STATE_DRAFT
    # only the genesis event exists
    assert len(campaign_store.list_state_events("camp_001", db_path=tmp_db)) == 1


def test_same_state_transition_is_noop(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    mgr.activate("camp_001")
    before = campaign_store.list_state_events("camp_001", db_path=tmp_db)
    res = mgr.transition("camp_001", STATE_ACTIVE)
    assert res.changed is False
    assert res.event_id is None
    after = campaign_store.list_state_events("camp_001", db_path=tmp_db)
    assert len(after) == len(before)   # no new event


def test_transition_unknown_campaign_raises(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    with pytest.raises(CampaignError):
        mgr.activate("ghost")


def test_terminal_state_stamps_completed_at(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    mgr.activate("camp_001")
    mgr.complete("camp_001", reason_code="goal_reached")
    c = campaign_store.get_campaign("camp_001", db_path=tmp_db)
    assert c["state"] == STATE_COMPLETED
    assert c["completed_at"] is not None


def test_full_lifecycle_path(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    assert mgr.activate("camp_001").to_state == STATE_ACTIVE
    assert mgr.mark_stalled("camp_001").to_state == STATE_STALLED
    assert mgr.activate("camp_001").to_state == STATE_ACTIVE
    assert mgr.archive("camp_001").to_state == STATE_ARCHIVED
    # archived campaigns may be revived
    assert mgr.activate("camp_001").to_state == STATE_ACTIVE
    assert mgr.is_terminal("camp_001") is False
    assert mgr.discard("camp_001").to_state == STATE_DISCARDED
    assert mgr.is_terminal("camp_001") is True


# ---------------------------------------------------------------------------
# progress derivation
# ---------------------------------------------------------------------------

def _enqueue_idea(db_path, idea_id, campaign_id, experiment_id=None):
    """Insert a minimal pending_ideas row tagged to a campaign."""
    from agents.storage.db import get_connection
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO pending_ideas "
            "(idea_id, hypothesis, suggested_signals, source_model, status, "
            " validation_ok, campaign_id, experiment_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (idea_id, "h", "[]", "test-model", "executed", 1,
             campaign_id, experiment_id),
        )
        conn.commit()


def test_count_campaign_experiments_only_counts_linked(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    _enqueue_idea(tmp_db, "i1", "camp_001", experiment_id="exp_1")
    _enqueue_idea(tmp_db, "i2", "camp_001", experiment_id=None)   # not run yet
    _enqueue_idea(tmp_db, "i3", "camp_002", experiment_id="exp_9")  # other camp
    n = campaign_store.count_campaign_experiments("camp_001", db_path=tmp_db)
    assert n == 1


def test_refresh_progress_updates_cache(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t", budget_experiments=2)
    _enqueue_idea(tmp_db, "i1", "camp_001", experiment_id="exp_1")
    n = mgr.refresh_progress("camp_001")
    assert n == 1
    c = campaign_store.get_campaign("camp_001", db_path=tmp_db)
    assert c["budget_spent"] == 1


def test_budget_exhausted(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t", budget_experiments=2)
    _enqueue_idea(tmp_db, "i1", "camp_001", experiment_id="exp_1")
    assert mgr.budget_exhausted("camp_001") is False
    _enqueue_idea(tmp_db, "i2", "camp_001", experiment_id="exp_2")
    assert mgr.budget_exhausted("camp_001") is True


def test_unbounded_budget_never_exhausts(tmp_db):
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t", budget_experiments=0)
    _enqueue_idea(tmp_db, "i1", "camp_001", experiment_id="exp_1")
    assert mgr.budget_exhausted("camp_001") is False


# ---------------------------------------------------------------------------
# Event log as source of truth (invariants 1-5)
# ---------------------------------------------------------------------------

def test_state_fully_reconstructible_from_events(tmp_db):
    """Invariant 1 & 2: authoritative state is derived from the event log, never
    from research_campaign.state."""
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    mgr.activate("camp_001")
    mgr.mark_stalled("camp_001")
    # Corrupt the projection cache to a wrong value.
    campaign_store.update_campaign_state("camp_001", STATE_COMPLETED, db_path=tmp_db)
    # The event-derived state ignores the corrupted cache.
    derived = campaign_store.reconstruct_state_from_events("camp_001", db_path=tmp_db)
    assert derived == STATE_STALLED
    assert mgr.current_state("camp_001") == STATE_STALLED


def test_transition_uses_event_log_not_cached_state(tmp_db):
    """Invariant 2: a corrupted cache does not let an illegal transition through
    nor block a legal one — legality is judged against the log."""
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    mgr.activate("camp_001")
    # Corrupt the cache to DRAFT; real state (per log) is ACTIVE.
    campaign_store.update_campaign_state("camp_001", STATE_DRAFT, db_path=tmp_db)
    # ACTIVE -> COMPLETED is legal per the log even though the cache says DRAFT.
    res = mgr.complete("camp_001")
    assert res.from_state == STATE_ACTIVE
    assert res.to_state == STATE_COMPLETED


def test_campaign_row_deletable_and_rebuildable_from_events(tmp_db):
    """Invariant 3: the projection row can be deleted and fully reconstructed
    from events (+ experiments), with no data loss of config or state."""
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign(
        "camp_001", "alt bars",
        goal_spec={"objective": "x"}, scope={"markets": ["India"]},
        budget_experiments=7, exploration_fraction=0.5, stall_patience=4,
    )
    mgr.activate("camp_001")
    _enqueue_idea(tmp_db, "i1", "camp_001", experiment_id="exp_1")
    before = campaign_store.get_campaign("camp_001", db_path=tmp_db)

    # Delete the projection row; the event log survives (no FK).
    campaign_store.delete_campaign_row("camp_001", db_path=tmp_db)
    assert campaign_store.get_campaign("camp_001", db_path=tmp_db) is None

    rebuilt = mgr.rebuild_from_events("camp_001")
    assert rebuilt["state"] == STATE_ACTIVE
    assert rebuilt["theme"] == before["theme"]
    assert rebuilt["goal_spec"] == before["goal_spec"]
    assert rebuilt["scope"] == before["scope"]
    assert rebuilt["budget_experiments"] == before["budget_experiments"]
    assert rebuilt["exploration_fraction"] == before["exploration_fraction"]
    assert rebuilt["stall_patience"] == before["stall_patience"]
    # budget_spent re-derived from the campaign-tagged experiment.
    assert rebuilt["budget_spent"] == 1


def test_reconcile_repairs_interrupted_transition(tmp_db):
    """Invariant 5: simulate a crash AFTER the event was appended but BEFORE the
    projection cache was updated; reconcile() repairs the stale cache."""
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t")
    mgr.activate("camp_001")
    # Emulate the interrupted transition: append the event only (log leads),
    # leaving the cache at ACTIVE.
    campaign_store.append_state_event(
        "camp_001", from_state=STATE_ACTIVE, to_state=STATE_STALLED,
        reason_code="no_progress", db_path=tmp_db)
    assert campaign_store.get_campaign("camp_001", db_path=tmp_db)["state"] == STATE_ACTIVE

    report = mgr.reconcile("camp_001")
    assert report["repaired"] is True
    assert report["authoritative_state"] == STATE_STALLED
    assert report["cached_state"] == STATE_ACTIVE
    assert campaign_store.get_campaign("camp_001", db_path=tmp_db)["state"] == STATE_STALLED


def test_reconcile_rebuilds_missing_row(tmp_db):
    """Invariant 5: reconcile() rebuilds a projection row that went missing."""
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("camp_001", "t", budget_experiments=3)
    mgr.activate("camp_001")
    campaign_store.delete_campaign_row("camp_001", db_path=tmp_db)
    report = mgr.reconcile("camp_001")
    assert report["row_existed"] is False
    assert report["repaired"] is True
    assert campaign_store.get_campaign("camp_001", db_path=tmp_db)["state"] == STATE_ACTIVE


def test_reconcile_all_is_noop_when_consistent(tmp_db):
    """reconcile_all() touches every campaign in the log and reports no repair
    needed when caches already agree."""
    mgr = CampaignManager(db_path=tmp_db)
    mgr.create_campaign("c1", "t")
    mgr.create_campaign("c2", "t")
    mgr.activate("c1")
    reports = mgr.reconcile_all()
    assert {r["campaign_id"] for r in reports} == {"c1", "c2"}
    assert all(r["repaired"] is False for r in reports)


def test_campaign_manager_is_sole_writer_of_campaign_tables(tmp_db):
    """Invariant 4 (static guard): no agents/ module other than campaign_store.py
    (the data-access layer the manager writes through) issues write SQL against
    the campaign tables."""
    import re
    from pathlib import Path

    agents_dir = Path(__file__).resolve().parent.parent
    write_sql = re.compile(
        r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
        r"(research_campaign|campaign_state_events)",
        re.IGNORECASE,
    )
    offenders = []
    for py in agents_dir.rglob("*.py"):
        # campaign_store.py is the sanctioned DAL; tests may construct fixtures.
        if py.name == "campaign_store.py" or "tests" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        if write_sql.search(text):
            offenders.append(str(py.relative_to(agents_dir)))
    assert offenders == [], f"unexpected campaign-table writers: {offenders}"
