"""
Tests for the read-only M10 campaign reporting surface
(agents/reporting/campaign_report_store.py + campaign_report.py).

Covers the six PR-9 requirements:
  * Reports are deterministic.
  * Reports perform no writes.
  * Reports reconstruct correctly from stored state.
  * Campaign statistics match underlying ledger data.
  * Exploration accounting matches scheduler evidence.
  * Hypothesis trees render correctly from stored lineage.

The package-wide read-only guards (no write-SQL, no execution-module imports)
in test_reporting.py glob reporting/*.py and therefore already cover the new
modules; these tests add the campaign-specific behavioural coverage.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage import campaign_store as cms
from agents.storage import scheduler_store as sched
from agents.storage import hypothesis_store as hs
from agents.storage import context_store as cs
from agents.storage import signal_store as ss
from agents.storage.ledger_store import upsert_experiment
from agents.storage.lessons_store import add_lesson

from agents.reporting import campaign_report_store as cap
from agents.reporting.campaign_report import generate_campaign_report
from agents.reporting import (
    campaign_overview_summary,
    campaign_ranking_summary,
    stalled_campaign_summary,
    exploration_summary,
    productive_context_summary,
    recent_knowledge_summary,
    signal_lifecycle_board_summary,
    hypothesis_tree_summary,
)
from agents.research_scheduler.scheduler import ResearchScheduler


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "campaign_report.db"
    create_all_tables(path)
    return path


def _campaign(db, cid, *, theme="theme", state=cms.STATE_ACTIVE,
              budget=10, spent=0, frac=0.34, stall_patience=3):
    cms.insert_campaign({
        "campaign_id": cid, "theme": theme, "state": state,
        "budget_experiments": budget, "budget_spent": spent,
        "exploration_fraction": frac, "stall_patience": stall_patience,
    }, db_path=db)
    cms.append_state_event(cid, from_state=None, to_state=cms.STATE_DRAFT,
                           db_path=db)
    cms.append_state_event(cid, from_state=cms.STATE_DRAFT, to_state=state,
                           db_path=db)


def _idea_with_experiment(db, idea_id, exp_id, cid, *, net_sharpe=None,
                          market="India", universe="NIFTY50"):
    """Insert an executed pending idea tagged to a campaign + its experiment."""
    upsert_experiment({
        "experiment_id": exp_id, "market": market, "universe": universe,
        "experiment_type": "portfolio", "status": "completed",
        **({"net_sharpe": net_sharpe} if net_sharpe is not None else {}),
    }, db_path=db)
    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO pending_ideas (idea_id, hypothesis, suggested_signals, "
            "source_model, market, universe, status, validation_ok, "
            "experiment_id, campaign_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (idea_id, "h", '["mom"]', "m", market, universe, "executed", 1,
             exp_id, cid),
        )
        conn.commit()


def _dispatch(db, idea_id, cid, bucket):
    sched.append_event(idea_id, sched.ACTION_DISPATCHED, campaign_id=cid,
                       evidence={"bucket": bucket}, db_path=db)


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------

def test_reports_are_deterministic(db):
    _campaign(db, "c1", theme="alpha")
    _campaign(db, "c2", theme="beta")
    _idea_with_experiment(db, "i1", "e1", "c1", net_sharpe=1.5)
    _idea_with_experiment(db, "i2", "e2", "c2", net_sharpe=0.5)
    _dispatch(db, "i1", "c1", "explore")
    _dispatch(db, "i2", "c2", "exploit")

    for fn in (
        lambda: campaign_ranking_summary(db_path=db),
        lambda: campaign_overview_summary(db_path=db),
        lambda: stalled_campaign_summary(db_path=db),
        lambda: productive_context_summary(db_path=db),
    ):
        assert fn() == fn()
    assert exploration_summary(db_path=db) == exploration_summary(db_path=db)


# ---------------------------------------------------------------------------
# 2. No writes
# ---------------------------------------------------------------------------

def test_reports_perform_no_writes(db):
    _campaign(db, "c1")
    _idea_with_experiment(db, "i1", "e1", "c1", net_sharpe=1.0)
    _dispatch(db, "i1", "c1", "explore")
    hs.insert_node({"node_id": "n1", "campaign_id": "c1", "root_id": "n1",
                    "hypothesis": "root"}, db_path=db)
    add_lesson("e1", "finding", "implication", db_path=db)

    tables = ("research_campaign", "campaign_state_events", "pending_ideas",
              "experiments", "scheduler_event", "hypothesis_node",
              "hypothesis_edge", "lessons_learned", "signal_library",
              "signal_context_observation")

    def snapshot():
        with get_connection(db) as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in tables}

    before = snapshot()
    campaign_overview_summary(db_path=db)
    campaign_ranking_summary(db_path=db)
    stalled_campaign_summary(db_path=db)
    exploration_summary(db_path=db)
    productive_context_summary(db_path=db)
    recent_knowledge_summary(db_path=db)
    signal_lifecycle_board_summary(db_path=db)
    hypothesis_tree_summary("c1", db_path=db)
    generate_campaign_report("c1", db_path=db)
    assert snapshot() == before


# ---------------------------------------------------------------------------
# 3. Reconstruct from stored state (event-log state, not projection row)
# ---------------------------------------------------------------------------

def test_overview_state_reconstructed_from_event_log(db):
    _campaign(db, "c1", state=cms.STATE_ACTIVE)
    # Drift the projection row away from the event log; the report must follow
    # the authoritative event log (STALLED), not the stale projection.
    cms.append_state_event("c1", from_state=cms.STATE_ACTIVE,
                           to_state=cms.STATE_STALLED, db_path=db)
    with get_connection(db) as conn:
        conn.execute("UPDATE research_campaign SET state=? WHERE campaign_id=?",
                     (cms.STATE_ACTIVE, "c1"))
        conn.commit()
    ov = campaign_overview_summary("c1", db_path=db)
    assert ov.state == cms.STATE_STALLED
    assert [s.campaign_id for s in stalled_campaign_summary(db_path=db)] == ["c1"]


# ---------------------------------------------------------------------------
# 4. Campaign statistics match underlying ledger data
# ---------------------------------------------------------------------------

def test_campaign_stats_match_ledger(db):
    _campaign(db, "c1")
    _idea_with_experiment(db, "i1", "e1", "c1", net_sharpe=2.0)
    _idea_with_experiment(db, "i2", "e2", "c1", net_sharpe=1.0)
    _idea_with_experiment(db, "i3", "e3", "c1", net_sharpe=None)

    ov = campaign_overview_summary("c1", db_path=db)
    assert ov.n_experiments == 3
    assert ov.n_with_net == 2
    assert ov.avg_net_sharpe == pytest.approx(1.5)
    assert ov.best_net_sharpe == pytest.approx(2.0)

    # Ranking productivity matches: more experiments ranks higher.
    _campaign(db, "c2")
    _idea_with_experiment(db, "j1", "f1", "c2", net_sharpe=5.0)
    ranking = campaign_ranking_summary(db_path=db)
    assert ranking[0].campaign_id == "c1"   # 3 experiments beats 1
    assert ranking[0].rank == 1 and ranking[1].rank == 2


# ---------------------------------------------------------------------------
# 5. Exploration accounting matches scheduler evidence
# ---------------------------------------------------------------------------

def test_exploration_accounting_matches_scheduler(db):
    _campaign(db, "c1")
    _dispatch(db, "i1", "c1", "explore")
    _dispatch(db, "i2", "c1", "exploit")
    _dispatch(db, "i3", "c1", "exploit")

    report = exploration_summary(db_path=db)
    scheduler = ResearchScheduler(db_path=db).exploration_stats()
    assert report.explore == scheduler["explore"] == 1
    assert report.exploit == scheduler["exploit"] == 2
    assert report.total == scheduler["total"] == 3
    assert report.explore_fraction == scheduler["explore_fraction"]

    # campaign-scoped filtering also matches
    scoped = exploration_summary("c1", db_path=db)
    assert scoped.total == 3 and scoped.campaign_id == "c1"


# ---------------------------------------------------------------------------
# 6. Hypothesis trees render from stored lineage
# ---------------------------------------------------------------------------

def test_hypothesis_tree_renders_from_lineage(db):
    _campaign(db, "c1")
    hs.insert_node({"node_id": "root", "campaign_id": "c1", "root_id": "root",
                    "depth": 0, "hypothesis": "root hypothesis"}, db_path=db)
    hs.insert_node({"node_id": "child", "campaign_id": "c1", "root_id": "root",
                    "parent_id": "root", "depth": 1,
                    "hypothesis": "child hypothesis",
                    "experiment_id": "e1"}, db_path=db)
    hs.insert_edge({"campaign_id": "c1", "parent_id": "root",
                    "child_id": "child", "operator": "refine"}, db_path=db)

    forest = hypothesis_tree_summary("c1", db_path=db)
    assert len(forest) == 1
    root = forest[0]
    assert root.node_id == "root" and root.parent_id is None
    assert len(root.children) == 1
    child = root.children[0]
    assert child.node_id == "child"
    assert child.operator_in == "refine"
    assert child.experiment_id == "e1"

    md = generate_campaign_report("c1", db_path=db)
    assert "root hypothesis" in md
    assert "child hypothesis" in md
    assert "_[refine]_" in md


# ---------------------------------------------------------------------------
# Lifecycle board + recent knowledge
# ---------------------------------------------------------------------------

def test_lifecycle_board_groups_by_state(db):
    ss.upsert_signal({"feature_name": "mom", "signal_type": "momentum",
                      "lifecycle_state": "promoted"}, db_path=db)
    ss.upsert_signal({"feature_name": "rev", "signal_type": "reversal",
                      "lifecycle_state": "observed"}, db_path=db)
    board = signal_lifecycle_board_summary(db_path=db)
    states = {b.lifecycle_state: b for b in board}
    assert states["promoted"].feature_names == ("mom",)
    assert states["observed"].feature_names == ("rev",)
    # promoted sorts before observed
    assert board[0].lifecycle_state == "promoted"


def test_recent_knowledge_lists_lessons(db):
    upsert_experiment({"experiment_id": "e1", "market": "India",
                       "universe": "NIFTY50", "experiment_type": "portfolio",
                       "status": "completed"}, db_path=db)
    add_lesson("e1", "alpha decays", "shorten lookback", category="signal",
               confidence="high", db_path=db)
    rows = recent_knowledge_summary(db_path=db)
    assert rows[0].finding == "alpha decays"
    assert rows[0].implication == "shorten lookback"
    assert rows[0].confidence == "high"


def test_empty_campaign_report_renders(db):
    md = generate_campaign_report(db_path=db)
    assert md.startswith("# Campaign Report")
    assert "_No campaigns._" in md
