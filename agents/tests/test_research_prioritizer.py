"""Tests for the Milestone 10 PR-5 ResearchPrioritizer.

Proves the PR-5 requirements:
  * every ranked idea carries a full score breakdown (EIG, Novelty, Memory,
    Campaign Priority, Cost);
  * the exploration quota is enforced;
  * high-value exploit ideas cannot crowd exploration out of the top_k window;
  * rankings are deterministic and identical inputs produce identical ordering.

The prioritizer is read-only: these tests never approve, execute, or schedule.
"""

from __future__ import annotations

import pytest

from agents.storage import (
    context_store, memory_store, campaign_store, ledger_store,
)
from agents.idea_generator import approval_queue
from agents.protocol import ProposedIdea
from agents.research_prioritizer import (
    ResearchPrioritizer,
    PrioritizerConfig,
    ScoreBreakdown,
    RankedIdea,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _idea(idea_id, signals, *, market="India", universe="NIFTY50",
          bar_type="time", campaign_id=None):
    return {
        "idea_id": idea_id,
        "suggested_signals": list(signals),
        "market": market,
        "universe": universe,
        "bar_type": bar_type,
        "campaign_id": campaign_id,
        "status": "pending",
    }


def _seed_cell(db, sig, market, universe, bar_type, n, net_sharpe=1.0):
    """Record n prior observations for a context cell so EIG reflects evidence."""
    for i in range(n):
        eid = f"e_{sig}_{market}_{bar_type}_{i}"
        ledger_store.upsert_experiment(
            {"experiment_id": eid, "hypothesis": "seed",
             "status": "completed", "bar_type": bar_type},
            db_path=db,
        )
        context_store.add_context_observation(
            experiment_id=eid,
            feature_name=sig, market=market, universe=universe,
            bar_type=bar_type, net_sharpe=net_sharpe, kept=1, db_path=db,
        )
    context_store.rebuild_context_cache(db, min_n=1)


def _campaign(db, cid, priority):
    campaign_store.insert_campaign(
        {"campaign_id": cid, "theme": "t", "goal_spec": {"priority": priority}},
        db_path=db,
    )


_CFG = PrioritizerConfig()


# ---------------------------------------------------------------------------
# Score breakdown
# ---------------------------------------------------------------------------

def test_breakdown_has_all_five_components(tmp_db):
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    b = p.score_idea(_idea("idea_1", ["mom_20"]))
    assert isinstance(b, ScoreBreakdown)
    d = b.as_dict()
    for key in ("expected_information_gain", "novelty", "memory_score",
                "campaign_priority", "cost", "research_value", "bucket"):
        assert key in d
    # All five components are in [0, 1].
    for key in ("expected_information_gain", "novelty", "memory_score",
                "campaign_priority", "cost", "research_value"):
        assert 0.0 <= d[key] <= 1.0


def test_every_ranked_idea_has_breakdown(tmp_db):
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    ideas = [_idea(f"idea_{i}", ["mom_20"], market=f"M{i}") for i in range(3)]
    ranked = p.rank(ideas)
    assert len(ranked) == 3
    for r in ranked:
        assert isinstance(r, RankedIdea)
        assert isinstance(r.breakdown, ScoreBreakdown)
        assert r.breakdown.bucket in ("explore", "exploit")


# ---------------------------------------------------------------------------
# Component behaviour (explainability sanity checks)
# ---------------------------------------------------------------------------

def test_eig_decreases_with_prior_evidence(tmp_db):
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    thin = p.score_idea(_idea("thin", ["sig_a"], market="A"))
    _seed_cell(tmp_db, "sig_b", "B", "NIFTY50", "time", n=5)
    thick = p.score_idea(_idea("thick", ["sig_b"], market="B"))
    assert thin.expected_information_gain > thick.expected_information_gain
    assert thin.bucket == "explore"
    assert thick.bucket == "exploit"


def test_novelty_decreases_with_siblings(tmp_db):
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    # Three ideas sharing the same (signal, market, universe, bar) key.
    dupes = [_idea(f"d{i}", ["mom_20"]) for i in range(3)]
    unique = _idea("u", ["rev_5"], market="US", universe="SP500")
    ranked = {r.idea_id: r for r in p.rank(dupes + [unique])}
    assert ranked["u"].breakdown.novelty == 1.0
    assert ranked["d0"].breakdown.novelty < 1.0
    # 3 siblings -> 1/(1+2) = 0.3333...
    assert ranked["d0"].breakdown.novelty == pytest.approx(1 / 3, abs=1e-6)


def test_campaign_priority_read_from_goal_spec(tmp_db):
    _campaign(tmp_db, "camp_hi", 1.0)
    _campaign(tmp_db, "camp_lo", 0.0)
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    hi = p.score_idea(_idea("i_hi", ["mom_20"], campaign_id="camp_hi"))
    lo = p.score_idea(_idea("i_lo", ["mom_20"], campaign_id="camp_lo"))
    none = p.score_idea(_idea("i_none", ["mom_20"]))
    assert hi.campaign_priority == 1.0
    assert lo.campaign_priority == 0.0
    assert none.campaign_priority == _CFG.default_campaign_priority


def test_memory_sentiment_moves_score(tmp_db):
    memory_store.add_memory(
        "India/NIFTY50/calm",
        "Signal 'mom_20' promoted; robust and generalises", confidence="high",
        db_path=tmp_db)
    memory_store.add_memory(
        "US/SP500/calm",
        "Signal 'rev_5' should retire; no edge, weak decay", confidence="high",
        db_path=tmp_db)
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    pos = p.score_idea(_idea("pos", ["mom_20"], market="India",
                             universe="NIFTY50"))
    neg = p.score_idea(_idea("neg", ["rev_5"], market="US", universe="SP500"))
    assert pos.memory_score > 0.5
    assert neg.memory_score < 0.5


def test_cost_cheaper_for_time_than_imbalance_bars(tmp_db):
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    cheap = p.score_idea(_idea("cheap", ["mom_20"], bar_type="time"))
    pricey = p.score_idea(_idea("pricey", ["mom_20"],
                                bar_type="dollar_imbalance"))
    # `cost` is cheapness in [0,1]: time bars score higher.
    assert cheap.cost > pricey.cost
    assert cheap.cost_estimate < pricey.cost_estimate


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_ranking_is_deterministic(tmp_db):
    _seed_cell(tmp_db, "sig_b", "B", "NIFTY50", "time", n=3)
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    ideas = [
        _idea("a", ["sig_a"], market="A"),
        _idea("b", ["sig_b"], market="B"),
        _idea("c", ["sig_c"], market="C", bar_type="volume"),
    ]
    r1 = [(r.idea_id, r.breakdown.research_value) for r in p.rank(ideas)]
    r2 = [(r.idea_id, r.breakdown.research_value) for r in p.rank(ideas)]
    assert r1 == r2


def test_identical_inputs_identical_ordering(tmp_db):
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    list_a = [_idea(f"x{i}", ["mom_20"], market=f"M{i}") for i in range(6)]
    list_b = [_idea(f"x{i}", ["mom_20"], market=f"M{i}") for i in range(6)]
    ra = p.rank(list_a)
    rb = p.rank(list_b)
    assert [r.idea_id for r in ra] == [r.idea_id for r in rb]
    assert [r.breakdown.as_dict() for r in ra] == \
           [r.breakdown.as_dict() for r in rb]


def test_value_ties_break_on_idea_id(tmp_db):
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    # Identical context -> identical value; only idea_id distinguishes them.
    ideas = [_idea("zeta", ["s"], market="X"),
             _idea("alpha", ["s"], market="X"),
             _idea("mu", ["s"], market="X")]
    order = [r.idea_id for r in p.rank(ideas)]
    assert order == sorted(order)  # alpha, mu, zeta


# ---------------------------------------------------------------------------
# Exploration quota
# ---------------------------------------------------------------------------

def _crowding_batch(db):
    """4 high-value exploit ideas + 3 low-value explore ideas.

    Exploit: distinct signals, time bars, n_prior=2 (EIG=0.333 -> exploit),
    campaign priority 1.0, unique sibling keys (novelty 1.0).
    Explore: shared signal/context (low novelty), n_prior=1 (EIG=0.5 -> explore),
    dollar_imbalance bars (expensive), no campaign. Built so each exploit idea
    out-scores every explore idea on Research Value.
    """
    _campaign(db, "camp_pri", 1.0)
    for i in range(4):
        _seed_cell(db, f"x{i}", "US", "SP500", "time", n=2)
    _seed_cell(db, "thin", "India", "NIFTY50", "dollar_imbalance", n=1)
    exploit = [
        _idea(f"exploit_{i}", [f"x{i}"], market="US", universe="SP500",
              bar_type="time", campaign_id="camp_pri")
        for i in range(4)
    ]
    explore = [
        _idea(f"explore_{i}", ["thin"], market="India", universe="NIFTY50",
              bar_type="dollar_imbalance")
        for i in range(3)
    ]
    return exploit, explore


def test_exploit_outscores_explore_without_quota(tmp_db):
    """Sanity: a pure value sort would put all exploit ideas on top."""
    exploit, explore = _crowding_batch(tmp_db)
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    ranked = p.rank(exploit + explore, top_k=4, exploration_fraction=0.0)
    top4 = ranked[:4]
    assert all(r.bucket == "exploit" for r in top4)


def test_exploration_quota_enforced(tmp_db):
    """With the quota on, the top_k window reserves explore slots."""
    exploit, explore = _crowding_batch(tmp_db)
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    # quota = ceil(0.34 * 4) = 2 explore ideas guaranteed in the top 4.
    ranked = p.rank(exploit + explore, top_k=4, exploration_fraction=0.34)
    top4 = ranked[:4]
    n_explore = sum(1 for r in top4 if r.bucket == "explore")
    assert n_explore >= 2


def test_exploit_cannot_crowd_out_exploration(tmp_db):
    """Even though every exploit idea out-scores every explore idea, explore
    ideas still appear inside the selection window once the quota is on."""
    exploit, explore = _crowding_batch(tmp_db)
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)

    # Confirm the premise: exploit really does out-score explore.
    by_id = {r.idea_id: r for r in p.rank(exploit + explore)}
    worst_exploit = min(by_id[f"exploit_{i}"].breakdown.research_value
                        for i in range(4))
    best_explore = max(by_id[f"explore_{i}"].breakdown.research_value
                       for i in range(3))
    assert worst_exploit > best_explore

    ranked = p.rank(exploit + explore, top_k=4, exploration_fraction=0.34)
    top_ids = {r.idea_id for r in ranked[:4]}
    assert any(eid.startswith("explore_") for eid in top_ids)


def test_quota_capped_by_available_explore(tmp_db):
    """If there are fewer explore ideas than the quota, we reserve only what
    exists and never fabricate or duplicate."""
    _seed_cell(tmp_db, "x0", "US", "SP500", "time", n=3)
    _seed_cell(tmp_db, "thin", "India", "NIFTY50", "time", n=0)
    exploit = [_idea(f"e{i}", ["x0"], market="US", universe="SP500")
               for i in range(5)]
    explore = [_idea("only_explore", ["thin"], market="India")]
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    ranked = p.rank(exploit + explore, top_k=4, exploration_fraction=0.5)
    ids = [r.idea_id for r in ranked]
    assert ids.count("only_explore") == 1          # no duplication
    assert len(ids) == len(set(ids)) == 6          # total order, all present


# ---------------------------------------------------------------------------
# DB integration (rank_pending) + read-only guarantee
# ---------------------------------------------------------------------------

def test_rank_pending_reads_queue_without_mutating(tmp_db):
    for i in range(3):
        idea = ProposedIdea(
            hypothesis=f"h{i}", suggested_signals=("mom_20",),
            source_model="t", rationale="r", market="India",
            universe="NIFTY50", bar_type="time")
        approval_queue.enqueue(idea, f"idea_{i}", db_path=tmp_db)

    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    ranked = p.rank_pending()
    assert len(ranked) == 3
    assert all(r.breakdown is not None for r in ranked)

    # The queue is untouched: still 3 pending, none approved/executing.
    pend = approval_queue.list_pending(db_path=tmp_db)
    assert len(pend) == 3
    assert approval_queue.list_approved(db_path=tmp_db) == []


def test_rank_pending_filters_by_campaign(tmp_db):
    _campaign(tmp_db, "camp_a", 0.8)
    a = ProposedIdea(hypothesis="ha", suggested_signals=("mom_20",),
                     source_model="t", rationale="r", market="India",
                     universe="NIFTY50", bar_type="time")
    approval_queue.enqueue(a, "idea_a", db_path=tmp_db)
    campaign_store.link_idea_to_campaign("idea_a", "camp_a", db_path=tmp_db)
    b = ProposedIdea(hypothesis="hb", suggested_signals=("rev_5",),
                     source_model="t", rationale="r", market="US",
                     universe="SP500", bar_type="time")
    approval_queue.enqueue(b, "idea_b", db_path=tmp_db)

    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    ranked = p.rank_pending(campaign_id="camp_a")
    assert [r.idea_id for r in ranked] == ["idea_a"]


def test_empty_input_returns_empty(tmp_db):
    p = ResearchPrioritizer(db_path=tmp_db, config=_CFG)
    assert p.rank([]) == []
    assert p.rank_pending() == []
