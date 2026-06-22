"""Tests for Milestone 10 PR-4 — bar_type plumbing and the ResearchStrategist.

Two concerns:

  A. bar_type is a first-class, typed field carried end-to-end:
       hypothesis_node -> pending_ideas -> ExperimentSpec -> config.json
                       -> experiments table
     never hidden inside `notes`.

  B. The ResearchStrategist deterministically evolves a campaign's hypothesis
     tree through the six operators, gated on M9 evidence, with explicit
     loop/explosion safeguards. The Alternative Bars campaign walks at least
     five generations:
        Time -> Volume -> Dollar -> Volume-Imbalance -> Cross-Market.
"""

import json
from dataclasses import asdict

import pytest

from agents import protocol
from agents.protocol import (
    ExperimentSpec,
    ProposedIdea,
    SUPPORTED_BAR_TYPES,
    normalize_bar_type,
    is_supported_bar_type,
)
from agents.storage import (
    campaign_store,
    hypothesis_store,
    context_store,
    ledger_store,
)
from agents.storage.db import get_connection
from agents.campaign_manager import CampaignManager
from agents.hypothesis_manager import HypothesisTreeManager, HypothesisTreeError
from agents.idea_generator import approval_queue
from agents.idea_generator.spec_builder import idea_to_spec
from agents.experiment_runner.folder_writer import write_config_json
from agents.quant_interface.ingestion import ingest_one
from agents.research_strategist import (
    ResearchStrategist,
    StrategistConfig,
    Proposal,
    StrategistError,
)
from agents.research_strategist.strategist import (
    OP_VARY_BAR,
    OP_CROSS_MARKET,
    OP_COMBINE,
    OP_NEGATE,
    OP_REFINE,
    OP_ADD_FILTER,
)


# ===========================================================================
# A. bar_type plumbing
# ===========================================================================

def test_supported_bar_types_vocabulary():
    assert SUPPORTED_BAR_TYPES == (
        "time", "volume", "dollar", "tick",
        "volume_imbalance", "dollar_imbalance",
    )
    for b in SUPPORTED_BAR_TYPES:
        assert is_supported_bar_type(b)
    assert not is_supported_bar_type("range")


def test_normalize_bar_type_defaults_and_validates():
    assert normalize_bar_type(None) == "time"
    assert normalize_bar_type("") == "time"
    assert normalize_bar_type("dollar") == "dollar"
    with pytest.raises(ValueError):
        normalize_bar_type("not_a_bar")


def test_experiment_spec_has_typed_bar_type_field():
    spec = ExperimentSpec(
        hypothesis="h", market="India", universe="NIFTY50", target="fwd_ret_5",
        features=["mom_20"], model="quantile_ranking",
        validation_method="walk_forward", success_criteria={"sharpe": 0.5},
        expected_improvement="x", bar_type="dollar",
    )
    record = asdict(spec)
    assert record["bar_type"] == "dollar"  # serialised, not hidden in notes
    assert "dollar" not in (spec.notes or "")


def test_proposed_idea_defaults_to_time_bar():
    idea = ProposedIdea(hypothesis="h", suggested_signals=("mom_20",),
                        source_model="m")
    assert idea.bar_type == "time"


def test_pending_ideas_persists_bar_type(tmp_db):
    idea = ProposedIdea(hypothesis="dollar bar momentum",
                        suggested_signals=("mom_20",), source_model="m",
                        market="India", universe="NIFTY50", bar_type="dollar")
    approval_queue.enqueue(idea, "idea_bar_1", db_path=tmp_db)
    with get_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT bar_type FROM pending_ideas WHERE idea_id='idea_bar_1'"
        ).fetchone()
    assert row["bar_type"] == "dollar"


def test_spec_builder_carries_bar_type_from_idea():
    spec = idea_to_spec({
        "idea_id": "idea_1", "hypothesis": "h", "market": "India",
        "universe": "NIFTY50", "suggested_signals": ["mom_20"],
        "bar_type": "volume", "source_model": "m",
    })
    assert spec.bar_type == "volume"


def test_spec_builder_defaults_bar_type_when_absent():
    spec = idea_to_spec({
        "idea_id": "idea_1", "hypothesis": "h", "market": "India",
        "universe": "NIFTY50", "suggested_signals": ["mom_20"],
        "source_model": "m",
    })
    assert spec.bar_type == "time"


def test_config_json_round_trips_bar_type(tmp_path):
    spec = ExperimentSpec(
        hypothesis="h", market="India", universe="NIFTY50", target="fwd_ret_5",
        features=["mom_20"], model="quantile_ranking",
        validation_method="walk_forward", success_criteria={"sharpe": 0.5},
        expected_improvement="x", bar_type="volume_imbalance",
    )
    write_config_json(tmp_path, spec, "exp_001")
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["bar_type"] == "volume_imbalance"


def test_ingestion_persists_bar_type_to_experiments(tmp_path, tmp_db):
    d = tmp_path / "exp_bar_ingest"
    d.mkdir()
    (d / "metrics.json").write_text(json.dumps({"sharpe": 1.1, "mdd": -0.2}))
    (d / "config.json").write_text(json.dumps(
        {"model": "quantile_ranking", "bar_type": "dollar"}))
    ingest_one(d, db_path=tmp_db)
    row = ledger_store.get_experiment("exp_bar_ingest", db_path=tmp_db)
    assert row["bar_type"] == "dollar"


def test_ingestion_defaults_bar_type_time_when_absent(tmp_path, tmp_db):
    d = tmp_path / "exp_no_bar"
    d.mkdir()
    (d / "metrics.json").write_text(json.dumps({"sharpe": 1.1}))
    (d / "config.json").write_text(json.dumps({"model": "quantile_ranking"}))
    ingest_one(d, db_path=tmp_db)
    row = ledger_store.get_experiment("exp_no_bar", db_path=tmp_db)
    assert row["bar_type"] == "time"


def test_hypothesis_node_rejects_unknown_bar_type(tmp_db):
    htm = HypothesisTreeManager(db_path=tmp_db)
    with pytest.raises(ValueError):
        htm.create_root("camp_x", "h", node_id="n1", signals=["mom_20"],
                        market="India", universe="NIFTY50", bar_type="bogus")


# ===========================================================================
# B. ResearchStrategist
# ===========================================================================

# Use min_n=1 so a single observation confirms a cell (keeps the worked walk
# to one experiment per generation).
_CFG = StrategistConfig(min_n=1)


def _active_campaign(db, cid="camp_bars", *, budget=0, scope=None):
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, "alternative bars", budget_experiments=budget,
                       scope=scope or {
                           "markets": ["India", "US"],
                           "universes": ["NIFTY50", "SP500"],
                           "bar_types": ["time", "volume", "dollar",
                                         "volume_imbalance"],
                       })
    cm.activate(cid, reason_code="kickoff")
    return cid


def _run_node(db, strat, node_id, *, net_sharpe=1.0):
    """Simulate the downstream M7→M9 flow for one node: stamp an experiment on
    the node, record a context observation under the node's bar_type, and
    rebuild the M9 cache so the strategist can read confirmation."""
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
        net_sharpe=net_sharpe, kept=1 if net_sharpe > 0 else 0, db_path=db,
    )
    context_store.rebuild_context_cache(db, min_n=1)
    return eid


def test_seed_creates_root_and_tagged_idea(tmp_db):
    cid = _active_campaign(tmp_db)
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    res = strat.seed(cid, "momentum on time bars", signals=["mom_20"],
                     market="India", universe="NIFTY50", bar_type="time")
    node = hypothesis_store.get_node(res.node_id, db_path=tmp_db)
    assert node["bar_type"] == "time"
    assert node["idea_id"] == res.idea_id
    # Idea is tagged to the campaign and carries bar_type.
    assert campaign_store.campaign_id_for_idea(res.idea_id, db_path=tmp_db) == cid
    with get_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT bar_type, status FROM pending_ideas WHERE idea_id=?",
            (res.idea_id,)).fetchone()
    assert row["bar_type"] == "time"
    assert row["status"] == "pending"  # human gate preserved


def test_propose_empty_when_not_active(tmp_db):
    cid = "camp_draft"
    cm = CampaignManager(db_path=tmp_db)
    cm.create_campaign(cid, "draft only")  # stays DRAFT
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    assert strat.propose(cid) == []


def test_propose_empty_when_budget_exhausted(tmp_db):
    cid = _active_campaign(tmp_db, "camp_budget", budget=1)
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    seed = strat.seed(cid, "momentum time", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    # Mark the seed idea executed so derived progress == budget (1).
    with get_connection(tmp_db) as conn:
        conn.execute("UPDATE pending_ideas SET experiment_id='exp_seed' "
                     "WHERE idea_id=?", (seed.idea_id,))
        conn.commit()
    _run_node(tmp_db, strat, seed.node_id)
    assert strat.campaigns.budget_exhausted(cid)
    assert strat.propose(cid) == []


def test_alternative_bars_five_generation_walk(tmp_db):
    cid = _active_campaign(tmp_db)
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)

    # G0: seed time bars, then "run" it (confirmed).
    seed = strat.seed(cid, "momentum on time bars", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    _run_node(tmp_db, strat, seed.node_id)

    seen_bars = ["time"]
    operators = []
    for _ in range(4):
        proposals = strat.propose(cid)
        assert len(proposals) == 1, f"expected one move, got {proposals}"
        p = proposals[0]
        operators.append(p.operator)
        results = strat.apply(cid, [p])
        new_node_id = results[0].node_id
        _run_node(tmp_db, strat, new_node_id)
        if p.operator == OP_VARY_BAR:
            seen_bars.append(p.bar_type)

    # Bars walked in order: time -> volume -> dollar -> volume_imbalance.
    assert seen_bars == ["time", "volume", "dollar", "volume_imbalance"]
    # Then a cross-market generalisation move (bars exhausted).
    assert operators == [OP_VARY_BAR, OP_VARY_BAR, OP_VARY_BAR, OP_CROSS_MARKET]

    # The cross-market child carries the winning bar and the new market.
    nodes = hypothesis_store.list_nodes(cid, db_path=tmp_db)
    xm = [n for n in nodes if n["origin_operator"] == OP_CROSS_MARKET][0]
    assert xm["bar_type"] == "volume_imbalance"
    assert xm["market"] == "US"
    assert xm["universe"] == "SP500"

    # Every generated idea is campaign-tagged and bar-typed.
    with get_connection(tmp_db) as conn:
        rows = conn.execute(
            "SELECT bar_type, campaign_id FROM pending_ideas").fetchall()
    assert all(r["campaign_id"] == cid for r in rows)
    assert {r["bar_type"] for r in rows} == {
        "time", "volume", "dollar", "volume_imbalance"}


def test_vary_bar_frontier_dedup_no_repeat(tmp_db):
    cid = _active_campaign(tmp_db, scope={
        "markets": ["India"], "universes": ["NIFTY50"],
        "bar_types": ["time", "volume"],
    })
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    seed = strat.seed(cid, "momentum time", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    _run_node(tmp_db, strat, seed.node_id)

    p1 = strat.propose(cid)
    assert len(p1) == 1 and p1[0].bar_type == "volume"
    res = strat.apply(cid, p1)
    _run_node(tmp_db, strat, res[0].node_id)

    # Bars exhausted (time, volume) and only one market in scope -> no moves.
    assert strat.propose(cid) == []


def test_max_depth_halts_expansion(tmp_db):
    cid = _active_campaign(tmp_db, scope={
        "markets": ["India"], "universes": ["NIFTY50"],
        "bar_types": ["time", "volume", "dollar", "volume_imbalance",
                      "tick", "dollar_imbalance"],
    })
    strat = ResearchStrategist(db_path=tmp_db, config=StrategistConfig(min_n=1, max_depth=2))
    seed = strat.seed(cid, "momentum time", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    _run_node(tmp_db, strat, seed.node_id)            # depth 0
    r1 = strat.apply(cid, strat.propose(cid))         # depth 1
    _run_node(tmp_db, strat, r1[0].node_id)
    r2 = strat.apply(cid, strat.propose(cid))         # depth 2
    _run_node(tmp_db, strat, r2[0].node_id)
    # depth-2 node is at max_depth -> not expandable.
    assert strat.propose(cid) == []


def test_unrun_node_is_not_expanded(tmp_db):
    cid = _active_campaign(tmp_db)
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    strat.seed(cid, "momentum time", signals=["mom_20"],
               market="India", universe="NIFTY50", bar_type="time")
    # No _run_node: the root has no experiment / no M9 confirmation.
    assert strat.propose(cid) == []


def test_negate_on_refuted_then_terminal(tmp_db):
    cid = _active_campaign(tmp_db, scope={
        "markets": ["India"], "universes": ["NIFTY50"],
        "bar_types": ["time"],
    })
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    seed = strat.seed(cid, "momentum time", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    _run_node(tmp_db, strat, seed.node_id, net_sharpe=-0.8)  # refuted

    proposals = strat.propose(cid)
    assert len(proposals) == 1 and proposals[0].operator == OP_NEGATE
    res = strat.apply(cid, proposals)
    neg = hypothesis_store.get_node(res[0].node_id, db_path=tmp_db)
    assert neg["origin_operator"] == OP_NEGATE

    # Even after "running" it, a negate node is terminal — no further proposals,
    # and the refuted parent is not negated twice.
    _run_node(tmp_db, strat, neg["node_id"], net_sharpe=-0.5)
    assert strat.propose(cid) == []


def test_combine_pairwise_confirmed_signals(tmp_db):
    cid = _active_campaign(tmp_db, scope={
        "markets": ["India"], "universes": ["NIFTY50"],
        "bar_types": ["time"],
    })
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    # Two independent confirmed roots in the same context, different signals.
    a = strat.tree.create_root(cid, "momentum", node_id="n_mom",
                               signals=["mom_20"], market="India",
                               universe="NIFTY50", bar_type="time")
    b = strat.tree.create_root(cid, "reversal", node_id="n_rev",
                               signals=["rev_5"], market="India",
                               universe="NIFTY50", bar_type="time")
    _run_node(tmp_db, strat, a["node_id"])
    _run_node(tmp_db, strat, b["node_id"])

    combines = [p for p in strat.propose(cid) if p.operator == OP_COMBINE]
    assert len(combines) == 1
    assert set(combines[0].signals) == {"mom_20", "rev_5"}
    assert len(combines[0].parent_node_ids) == 2

    res = strat.apply(cid, combines)
    child = hypothesis_store.get_node(res[0].node_id, db_path=tmp_db)
    assert child["origin_operator"] == OP_COMBINE
    parents = hypothesis_store.parents_of(child["node_id"], db_path=tmp_db)
    assert len(parents) == 2 and all(e["operator"] == OP_COMBINE for e in parents)

    # Frontier dedup: the same pair is not combined again.
    assert [p for p in strat.propose(cid) if p.operator == OP_COMBINE] == []


def test_apply_supports_refine_and_add_filter(tmp_db):
    """refine and add_filter are interface-complete via apply, even though their
    auto-triggers are out of PR-4 scope."""
    cid = _active_campaign(tmp_db)
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    seed = strat.seed(cid, "momentum time", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")

    for op in (OP_REFINE, OP_ADD_FILTER):
        p = Proposal(operator=op, parent_node_ids=[seed.node_id],
                     hypothesis=f"{op} child", bar_type="time",
                     market="India", universe="NIFTY50", signals=["mom_20"],
                     rationale="explicit")
        res = strat.apply(cid, [p])
        child = hypothesis_store.get_node(res[0].node_id, db_path=tmp_db)
        assert child["origin_operator"] == op
        assert child["bar_type"] == "time"
        # Idea tagged + bar-typed.
        assert campaign_store.campaign_id_for_idea(
            res[0].idea_id, db_path=tmp_db) == cid


def test_proposal_rejects_unknown_operator():
    with pytest.raises(StrategistError):
        Proposal(operator="explode", parent_node_ids=[], hypothesis="h",
                 bar_type="time", market="India", universe="NIFTY50",
                 signals=["mom_20"], rationale="x")


def test_seed_is_idempotent_guard(tmp_db):
    cid = _active_campaign(tmp_db)
    strat = ResearchStrategist(db_path=tmp_db, config=_CFG)
    strat.seed(cid, "root", signals=["mom_20"], market="India",
               universe="NIFTY50", bar_type="time")
    with pytest.raises(StrategistError):
        strat.seed(cid, "root again", signals=["mom_20"], market="India",
                   universe="NIFTY50", bar_type="time")
