"""Tests for Milestone 10 PR-8 — exploration quota + anti-mode-collapse.

Proves the PR-8 requirements:

  * Exploit candidates cannot consume all approval slots — the exploration
    quota reserves slots for explore ideas even when exploit ideas score higher.
  * The exploration quota is always respected (across window sizes / fractions).
  * Exploration candidates are selected from under-sampled M9 contexts.
  * Repeated expansion from the same hypothesis frontier is bounded.
  * Deterministic ranking is preserved (identical state ⇒ identical plan).
  * Restart/recovery preserves quota state (accounting is reconstructed purely
    from the append-only scheduler_event log).

Three layers are exercised: the pure ExplorationPlanner, the ResearchScheduler
that wires it into the dispatch plan, and the ResearchStrategist frontier bound.
Nothing here approves or executes anything — the human gate is untouched.
"""

from __future__ import annotations

import json
import math

import pytest

from agents.storage import (
    scheduler_store, campaign_store, ledger_store, context_store,
)
from agents.storage.db import get_connection
from agents.campaign_manager import CampaignManager
from agents.research_quota import (
    ExplorationPlanner, QuotaConfig, Candidate,
    BUCKET_EXPLORE, BUCKET_EXPLOIT,
)
from agents.research_scheduler import ResearchScheduler, SchedulerConfig
from agents.research_strategist import ResearchStrategist, StrategistConfig
from agents.storage import hypothesis_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approved(db, idea_id, *, signals, market="India", universe="NIFTY50",
              bar_type="time", campaign_id=None, status="approved"):
    """Insert a pending_ideas row already past the human gate (approved)."""
    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO pending_ideas
                (idea_id, hypothesis, suggested_signals, source_model,
                 market, universe, bar_type, metadata, status, validation_ok,
                 validation_reasons, experiment_id, campaign_id, created_at)
            VALUES (?, ?, ?, 'test', ?, ?, ?, '{}', ?, 1, '[]', NULL, ?, ?)
            """,
            (idea_id, f"hyp {idea_id}", json.dumps(list(signals)),
             market, universe, bar_type, status, campaign_id,
             "2026-01-01T00:00:00"),
        )
        conn.commit()


def _seed_cell(db, sig, *, market="India", universe="NIFTY50",
               bar_type="time", n=5, net_sharpe=1.0):
    """Record n prior observations so the (sig, market, universe, bar) cell is
    *well-sampled* ⇒ low EIG ⇒ exploit bucket."""
    for i in range(n):
        eid = f"e_{sig}_{market}_{bar_type}_{i}"
        ledger_store.upsert_experiment(
            {"experiment_id": eid, "hypothesis": "seed",
             "status": "completed", "bar_type": bar_type},
            db_path=db,
        )
        context_store.add_context_observation(
            experiment_id=eid, feature_name=sig, market=market,
            universe=universe, bar_type=bar_type, net_sharpe=net_sharpe,
            kept=1, db_path=db,
        )
    context_store.rebuild_context_cache(db, min_n=1)


def _cand(idea_id, bucket, order, *, ctx=None):
    return Candidate(
        idea_id=idea_id, bucket=bucket,
        context_key=ctx if ctx is not None else (idea_id, "m", "u", "time"),
        order=order,
    )


# ===========================================================================
# Pure ExplorationPlanner
# ===========================================================================

def test_exploit_cannot_consume_all_slots():
    """Top-of-ranking exploit ideas must not crowd exploration out of the
    window: with frac high enough to reserve a slot, an explore candidate that
    ranks BELOW every exploit candidate is still selected."""
    planner = ExplorationPlanner(QuotaConfig(exploration_fraction=0.34,
                                             max_per_context=None))
    cands = [
        _cand("x0", BUCKET_EXPLOIT, 0),
        _cand("x1", BUCKET_EXPLOIT, 1),
        _cand("x2", BUCKET_EXPLOIT, 2),
        _cand("e0", BUCKET_EXPLORE, 3),   # lowest value, but explore
    ]
    plan = planner.plan(cands, window=3)
    assert len(plan.selected) == 3
    # ceil(0.34*3) = 2 explore reserved, but only 1 explore exists ⇒ it is in.
    assert "e0" in plan.explore_selected
    assert plan.exploit_count == 2          # one exploit displaced by the quota


@pytest.mark.parametrize("window", [1, 2, 3, 4, 5, 8])
@pytest.mark.parametrize("frac", [0.0, 0.25, 0.34, 0.5, 1.0])
def test_exploration_quota_always_respected(window, frac):
    """For any window/fraction, the number of explore ideas selected is at least
    min(quota, available explore) — the quota is never under-filled when explore
    candidates exist."""
    planner = ExplorationPlanner(QuotaConfig(exploration_fraction=frac,
                                             max_per_context=None))
    # 4 exploit (top), 4 explore (bottom) — exploit would win on pure value.
    cands = [_cand(f"x{i}", BUCKET_EXPLOIT, i) for i in range(4)]
    cands += [_cand(f"e{i}", BUCKET_EXPLORE, 4 + i) for i in range(4)]
    plan = planner.plan(cands, window=window)
    quota = math.ceil(frac * window)
    available = min(4, window)
    assert plan.explore_count >= min(quota, available)
    assert len(plan.selected) == min(window, len(cands))


def test_context_diversity_caps_one_context():
    """No more than max_per_context selected ideas share a context key, even
    when they dominate the value ranking."""
    planner = ExplorationPlanner(QuotaConfig(exploration_fraction=0.0,
                                             max_per_context=2))
    same = ("mom", "m", "u", "time")
    cands = [_cand(f"a{i}", BUCKET_EXPLOIT, i, ctx=same) for i in range(4)]
    cands += [_cand("b0", BUCKET_EXPLOIT, 4, ctx=("rev", "m", "u", "time"))]
    plan = planner.plan(cands, window=4)
    shared = [c for c in plan.selected if c.context_key == same]
    assert len(shared) == 2                      # capped
    assert "b0" in [c.idea_id for c in plan.selected]
    assert {"a2", "a3"} & set(plan.dropped_for_context)


def test_planner_is_deterministic():
    planner = ExplorationPlanner(QuotaConfig(exploration_fraction=0.34))
    cands = [_cand(f"x{i}", BUCKET_EXPLOIT, i) for i in range(3)]
    cands += [_cand(f"e{i}", BUCKET_EXPLORE, 3 + i) for i in range(3)]
    a = planner.plan(cands, window=4).as_dict()["selected"]
    b = planner.plan(cands, window=4).as_dict()["selected"]
    assert a == b


def test_admission_predicate_only_fires_on_selection():
    """The accept callback must consume budget only for ideas actually selected
    (so per-campaign budget accounting stays exact)."""
    planner = ExplorationPlanner(QuotaConfig(exploration_fraction=0.0,
                                             max_per_context=None))
    consumed = []

    def accept(c):
        if len(consumed) >= 2:        # budget of 2
            return False
        consumed.append(c.idea_id)
        return True

    cands = [_cand(f"x{i}", BUCKET_EXPLOIT, i) for i in range(5)]
    plan = planner.plan(cands, window=5, accept=accept)
    assert len(plan.selected) == 2
    assert consumed == [c.idea_id for c in plan.selected]
    assert len(plan.dropped_for_admission) >= 1


# ===========================================================================
# ResearchScheduler integration
# ===========================================================================

def test_scheduler_quota_reserves_explore_over_exploit(tmp_db):
    """In a real dispatch plan, well-sampled (exploit) ideas cannot fill the
    whole window — at least one under-sampled (explore) idea is reserved."""
    db = tmp_db
    # Three well-sampled signals ⇒ exploit; they rank high on EIG-free value.
    for s in ("mom", "rev", "val"):
        _seed_cell(db, s, n=6)
        _approved(db, f"i_{s}", signals=(s,))
    # Two fresh signals ⇒ explore (no prior experiments in their cells).
    _approved(db, "i_new1", signals=("brandnew1",))
    _approved(db, "i_new2", signals=("brandnew2",))

    s = ResearchScheduler(db, config=SchedulerConfig(
        exploration_fraction=0.5, max_per_context=None))
    plan = s.experiment_queue(limit=3)
    buckets = {d.idea_id: d.bucket for d in plan}
    assert len(plan) == 3
    assert sum(1 for b in buckets.values() if b == "explore") >= 1


def test_explore_bucket_targets_under_sampled_contexts(tmp_db):
    """Every idea the scheduler classifies 'explore' targets a context with few
    prior experiments; every 'exploit' targets a well-sampled one."""
    db = tmp_db
    _seed_cell(db, "mom", n=6)           # well-sampled
    _approved(db, "i_mom", signals=("mom",))
    _approved(db, "i_fresh", signals=("fresh_sig",))   # under-sampled

    s = ResearchScheduler(db, config=SchedulerConfig(max_per_context=None))
    plan = {d.idea_id: d for d in s.experiment_queue()}
    assert plan["i_mom"].bucket == "exploit"
    assert plan["i_fresh"].bucket == "explore"


def test_scheduler_context_diversity_caps_dispatch(tmp_db):
    """Many approved ideas in ONE context cannot all be dispatched in a tick."""
    db = tmp_db
    for n in range(5):
        # Same signal/market/universe/bar ⇒ identical context key.
        _approved(db, f"dup{n}", signals=("mom",))
    s = ResearchScheduler(db, config=SchedulerConfig(max_per_context=2))
    plan = s.experiment_queue()
    assert len(plan) == 2


def test_scheduler_plan_deterministic_with_quota(tmp_db):
    db = tmp_db
    for s_ in ("mom", "rev", "val"):
        _seed_cell(db, s_, n=6)
        _approved(db, f"i_{s_}", signals=(s_,))
    _approved(db, "i_new", signals=("freshie",))
    s = ResearchScheduler(db, config=SchedulerConfig(exploration_fraction=0.5))
    p1 = [d.idea_id for d in s.experiment_queue(limit=3)]
    p2 = [d.idea_id for d in s.experiment_queue(limit=3)]
    assert p1 == p2


def test_exploration_stats_reconstructed_after_restart(tmp_db):
    """Campaign-level exploration accounting is derived purely from the
    append-only log, so a fresh scheduler instance reports identical numbers."""
    db = tmp_db
    _seed_cell(db, "mom", n=6)
    _approved(db, "i_mom", signals=("mom",))
    _approved(db, "i_fresh", signals=("freshie",))

    s = ResearchScheduler(db, config=SchedulerConfig(max_per_context=None))
    s.dispatch(limit=5)                       # writes dispatched events w/ bucket
    stats_before = s.exploration_stats()
    assert stats_before["total"] == 2
    assert stats_before["explore"] == 1
    assert stats_before["exploit"] == 1

    # Simulate a process restart: brand-new instance, same DB.
    s2 = ResearchScheduler(db)
    assert s2.exploration_stats() == stats_before


# ===========================================================================
# ResearchStrategist frontier-expansion bound
# ===========================================================================

def _active_campaign(db, cid="camp_pr8", budget=0):
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, "frontier bound", budget_experiments=budget,
                       scope={"markets": ["India", "US"],
                              "universes": ["NIFTY50", "SP500"],
                              "bar_types": ["time", "volume", "dollar",
                                            "tick", "volume_imbalance"]})
    cm.activate(cid, reason_code="kickoff")
    return cid


def _run_node(db, strat, node_id, *, net_sharpe=1.0):
    node = hypothesis_store.get_node(node_id, db_path=db)
    eid = f"exp_{node_id}"
    ledger_store.upsert_experiment(
        {"experiment_id": eid, "hypothesis": node["hypothesis"],
         "status": "completed", "bar_type": node["bar_type"]},
        db_path=db,
    )
    strat.tree.link_experiment(node_id, eid)
    sigs = node.get("signals") or []
    sig = sigs[0] if isinstance(sigs, list) and sigs else "mom_20"
    context_store.add_context_observation(
        experiment_id=eid, feature_name=sig, market=node["market"],
        universe=node["universe"], bar_type=node["bar_type"],
        net_sharpe=net_sharpe, kept=1, db_path=db,
    )
    context_store.rebuild_context_cache(db, min_n=1)
    return eid


def test_repeated_frontier_expansion_is_bounded(tmp_db):
    """A single confirmed frontier node can spawn at most
    max_children_per_frontier children across ticks, even if the strategist
    would otherwise keep proposing vary_bar moves from it."""
    db = tmp_db
    cid = _active_campaign(db)
    strat = ResearchStrategist(
        db_path=db,
        config=StrategistConfig(min_n=1, max_children_per_frontier=2, max_depth=12),
    )
    seed = strat.seed(cid, "momentum on time bars", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    _run_node(db, strat, seed.node_id)        # root confirmed ⇒ frontier

    # Apply proposals repeatedly WITHOUT confirming the new children, so the
    # frontier stays pinned to the root: the only thing that can stop it is the
    # frontier-expansion bound.
    total_applied = 0
    for _ in range(6):
        proposals = strat.propose(cid)
        if not proposals:
            break
        strat.apply(cid, proposals)
        total_applied += len(proposals)

    children = hypothesis_store.children_of(seed.node_id, db_path=db)
    assert len(children) == 2                  # capped at max_children_per_frontier
    # And once capped, the root is no longer expandable.
    root = hypothesis_store.get_node(seed.node_id, db_path=db)
    assert strat._expandable(root) is False


def test_frontier_bound_is_deterministic(tmp_db):
    """Two strategists over identical state make identical frontier decisions."""
    db = tmp_db
    cid = _active_campaign(db)
    strat = ResearchStrategist(
        db_path=db, config=StrategistConfig(min_n=1, max_children_per_frontier=2))
    seed = strat.seed(cid, "momentum time", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    _run_node(db, strat, seed.node_id)
    p1 = [p.operator for p in strat.propose(cid)]
    p2 = [p.operator for p in ResearchStrategist(
        db_path=db,
        config=StrategistConfig(min_n=1, max_children_per_frontier=2)).propose(cid)]
    assert p1 == p2
