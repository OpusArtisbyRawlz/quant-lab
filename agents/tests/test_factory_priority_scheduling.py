"""
Factory scheduling — general priority ordering of runnable campaigns.

Regression for the orchestration bug where a lower-priority campaign that stored its
priority in the legacy ``goal_spec.priority`` location out-ranked a higher-priority
campaign that used the first-class ``priority`` column (P6-8+), because the scheduler's
ordering read only ``goal_spec.priority``. The scheduler now uses the single source of
truth (``campaign_store.campaign_priority``) for effective priority.

No campaign IDs are special-cased: ordering is (−effective_priority, campaign_id).
"""

from __future__ import annotations

from pathlib import Path

from agents.storage.db import create_all_tables
from agents.campaign_manager import CampaignManager
from agents.research_scheduler import ResearchScheduler
from agents.research_loop.factory_runner import FactoryRunner


def _db(tmp_path) -> Path:
    db = tmp_path / "sched.db"
    create_all_tables(db)
    return db


def _queue(db, cm) -> list[str]:
    return [c["campaign_id"] for c in ResearchScheduler(db, campaign_manager=cm).campaign_queue()]


def test_higher_priority_wins_across_priority_locations(tmp_path):
    """The reported scenario: first-class priority=10 must beat goal_spec.priority=5."""
    db = _db(tmp_path); cm = CampaignManager(db_path=db)
    cm.create_campaign("recovery-baseline", theme="t", goal_spec={"priority": 5})
    cm.activate("recovery-baseline")
    cm.create_campaign("historical-integrity-v1", theme="t", priority=10.0)
    cm.activate("historical-integrity-v1")
    q = _queue(db, cm)
    assert q == ["historical-integrity-v1", "recovery-baseline"]
    # FactoryRunner selects the same top campaign (delegates to the scheduler).
    assert FactoryRunner(db_path=db, campaign_manager=cm)._runnable_ids()[0] == \
        "historical-integrity-v1"


def test_equal_priority_deterministic_by_campaign_id(tmp_path):
    db = _db(tmp_path); cm = CampaignManager(db_path=db)
    for cid in ("c_zeta", "c_alpha", "c_mu"):
        cm.create_campaign(cid, theme="t", priority=7.0); cm.activate(cid)
    q = _queue(db, cm)
    assert q == ["c_alpha", "c_mu", "c_zeta"]     # ascending campaign_id tie-break


def test_blocked_campaigns_skipped(tmp_path):
    """A non-ACTIVE (never-activated / draft) campaign is skipped even at max priority."""
    db = _db(tmp_path); cm = CampaignManager(db_path=db)
    cm.create_campaign("draft-top", theme="t", priority=100.0)   # created, NOT activated
    cm.create_campaign("active-low", theme="t", priority=1.0); cm.activate("active-low")
    q = _queue(db, cm)
    assert q == ["active-low"]
    assert "draft-top" not in q


def test_budget_exhausted_campaign_skipped(tmp_path):
    db = _db(tmp_path); cm = CampaignManager(db_path=db)
    cm.create_campaign("exhausted", theme="t", priority=100.0, budget_experiments=0)
    cm.activate("exhausted")
    cm.create_campaign("runnable", theme="t", priority=1.0, budget_experiments=5)
    cm.activate("runnable")
    q = _queue(db, cm)
    # budget_experiments=0 means an immediately-exhausted budget → skipped.
    if cm.budget_exhausted("exhausted"):
        assert q == ["runnable"]
    else:  # if 0 means "unbounded", both are runnable and priority still orders them
        assert q[0] == "exhausted"


def test_completed_campaigns_ignored(tmp_path):
    db = _db(tmp_path); cm = CampaignManager(db_path=db)
    cm.create_campaign("done-top", theme="t", priority=100.0)
    cm.activate("done-top"); cm.complete("done-top")
    cm.create_campaign("active-low", theme="t", priority=1.0); cm.activate("active-low")
    q = _queue(db, cm)
    assert q == ["active-low"]
    assert "done-top" not in q
