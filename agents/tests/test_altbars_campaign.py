"""
M10 PR-10 — Alternative Bars worked campaign: end-to-end validation.

This is the worked-example integration test for the whole Milestone 10 stack. It
drives a single campaign through every M10 component and asserts the architecture
holds together end to end:

    CampaignManager  -> creates/activates the campaign (event-sourced state)
    ResearchStrategist -> evolves the hypothesis tree (Time -> Volume -> Dollar
                          -> Volume-Imbalance -> Cross-Market) via the six
                          deterministic operators, gated on M9 evidence
    human approval gate -> every generated idea is pending until approved
    ResearchScheduler  -> ranks the approved pool, enforces the exploration quota
                          and per-context diversity, records dispatch decisions
    ResearchLoop       -> runs the deterministic six-phase tick over the real M7
                          executor (synthetic data), with recovery + checkpoints
    CampaignReporter   -> renders the read-only campaign board from stored state

The hypothesis-tree walk drives M9 confirmation deterministically (the same
``_run_node`` pattern the PR-4 strategist tests use) so the worked campaign is
reproducible; the loop tests exercise the *real* executor so the M7 path,
recovery, and checkpoint logic are genuinely end-to-end. Nothing here performs
statistical validation, auto-approval, or production-readiness checks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.protocol import ProposedIdea
from agents.storage.db import create_all_tables, get_connection
from agents.storage import (
    campaign_store,
    hypothesis_store,
    context_store,
    ledger_store,
    scheduler_store,
    loop_store,
)
from agents.campaign_manager import CampaignManager
from agents.campaign_manager.manager import (
    STATE_ACTIVE, STATE_DRAFT, STATE_STALLED,
)
from agents.hypothesis_manager import (
    OP_VARY_BAR, OP_CROSS_MARKET, OP_NEGATE, OP_COMBINE,
)
from agents.research_strategist import ResearchStrategist, StrategistConfig
from agents.research_scheduler import ResearchScheduler, SchedulerConfig
from agents.research_loop import ResearchLoop, LoopConfig
from agents.idea_generator import approval_queue as q
from agents.idea_generator import idea_executor, scoring
from agents.reporting import (
    campaign_overview_summary,
    campaign_ranking_summary,
    stalled_campaign_summary,
    exploration_summary,
    productive_context_summary,
    signal_lifecycle_board_summary,
    hypothesis_tree_summary,
    generate_campaign_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "altbars.db"
    create_all_tables(path)
    return path


@pytest.fixture
def completed_dir(tmp_path):
    d = tmp_path / "completed"
    d.mkdir()
    return d


@pytest.fixture
def data_root(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    return d


# Deterministic synthetic OHLCV so the real M7 executor never touches the network.
def _make_data_dict(n_dates=80, n_tickers=10, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    out = {}
    for i in range(n_tickers):
        prices = 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, n_dates))
        df = pd.DataFrame({
            "Open": prices * rng.uniform(0.99, 1.00, n_dates),
            "High": prices * rng.uniform(1.00, 1.01, n_dates),
            "Low": prices * rng.uniform(0.98, 1.00, n_dates),
            "Close": prices,
            "Volume": rng.integers(500_000, 2_000_000, n_dates).astype(float),
        }, index=dates)
        df.index.name = "Date"
        out[f"T{i:02d}"] = df
    return out


def _provider(spec):
    return _make_data_dict()


# Worked-campaign scope: the Alternative Bars bar-type ladder + a second market.
SCOPE = {
    "markets": ["India", "US"],
    "universes": ["NIFTY50", "SP500"],
    "bar_types": ["time", "volume", "dollar", "volume_imbalance"],
}
_CFG = StrategistConfig(min_n=1)   # one confirmed observation per generation


# ---------------------------------------------------------------------------
# Worked-campaign harness
# ---------------------------------------------------------------------------

def _create_campaign(db, cid="altbars", *, budget=0, scope=None):
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, "Alternative Bars",
                       goal_spec={"priority": 0.7},
                       scope=scope or SCOPE,
                       budget_experiments=budget)
    cm.activate(cid, reason_code="kickoff")
    return cid


def _confirm_node(db, strat, node_id, *, net_sharpe=1.0):
    """Simulate the downstream M7 -> M9 flow for one hypothesis node: stamp an
    experiment on the node, record a context observation under the node's bar
    type, and rebuild the M9 cache so the strategist reads confirmation. Mirrors
    the established PR-4 worked-walk pattern so the campaign evolves
    deterministically."""
    node = hypothesis_store.get_node(node_id, db_path=db)
    eid = f"exp_{node_id}"
    ledger_store.upsert_experiment(
        {"experiment_id": eid, "hypothesis": node["hypothesis"],
         "market": node["market"], "universe": node["universe"],
         "status": "completed", "bar_type": node["bar_type"],
         "net_sharpe": net_sharpe},
        db_path=db,
    )
    strat.tree.link_experiment(node_id, eid)
    # Stamp the node's idea with the experiment + executed status so campaign
    # attribution (pending_ideas.experiment_id) and budget accounting see it,
    # exactly as the real executor would on a live run.
    if node.get("idea_id"):
        with get_connection(db) as conn:
            conn.execute(
                "UPDATE pending_ideas SET experiment_id=?, status='executed' "
                "WHERE idea_id=?", (eid, node["idea_id"]))
            conn.commit()
    sigs = node.get("signals") or []
    sig = sigs[0] if isinstance(sigs, list) and sigs else "mom_20"
    context_store.add_context_observation(
        experiment_id=eid, feature_name=sig, market=node["market"],
        universe=node["universe"], bar_type=node["bar_type"],
        net_sharpe=net_sharpe, kept=1 if net_sharpe > 0 else 0, db_path=db,
    )
    context_store.rebuild_context_cache(db, min_n=1)
    return eid


def _walk_altbars(db, cid):
    """Drive the full Alternative Bars worked walk and return (strat, operators,
    bars). G0 seeds Time bars; four further generations evolve the frontier."""
    strat = ResearchStrategist(db_path=db, config=_CFG)
    seed = strat.seed(cid, "momentum on time bars", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    _confirm_node(db, strat, seed.node_id)
    operators, bars = [], ["time"]
    for _ in range(4):
        proposals = strat.propose(cid)
        assert len(proposals) == 1, f"expected one move, got {proposals}"
        p = proposals[0]
        operators.append(p.operator)
        res = strat.apply(cid, [p])
        _confirm_node(db, strat, res[0].node_id)
        if p.operator == OP_VARY_BAR:
            bars.append(p.bar_type)
    return strat, operators, bars


# ===========================================================================
# 1. Campaign creates successfully
# ===========================================================================

def test_campaign_creates_successfully(db):
    cid = _create_campaign(db)
    # State is reconstructed from the event log, not the projection row.
    assert campaign_store.reconstruct_state_from_events(cid, db_path=db) == STATE_ACTIVE
    camp = campaign_store.get_campaign(cid, db_path=db)
    assert camp["theme"] == "Alternative Bars"
    assert camp["scope"]["bar_types"][0] == "time"
    # The genesis (DRAFT) + activate (ACTIVE) transitions are both logged.
    states = [e["to_state"] for e in campaign_store.list_state_events(cid, db_path=db)]
    assert states[0] == STATE_DRAFT and states[-1] == STATE_ACTIVE


# ===========================================================================
# 2. Hypothesis tree evolves as expected (Time -> Vol -> Dollar -> VolImb -> XM)
# ===========================================================================

def test_hypothesis_tree_evolves_as_expected(db):
    cid = _create_campaign(db)
    strat, operators, bars = _walk_altbars(db, cid)

    # The bar-type ladder is walked in order, then a cross-market generalisation.
    assert bars == ["time", "volume", "dollar", "volume_imbalance"]
    assert operators == [OP_VARY_BAR, OP_VARY_BAR, OP_VARY_BAR, OP_CROSS_MARKET]

    # The cross-market child carries the winning bar and the second market.
    nodes = hypothesis_store.list_nodes(cid, db_path=db)
    xm = [n for n in nodes if n["origin_operator"] == OP_CROSS_MARKET][0]
    assert xm["bar_type"] == "volume_imbalance"
    assert xm["market"] == "US" and xm["universe"] == "SP500"

    # Every generated idea is campaign-tagged and bar-typed (no bar hidden in text).
    with get_connection(db) as conn:
        rows = conn.execute(
            "SELECT bar_type, campaign_id FROM pending_ideas").fetchall()
    assert all(r["campaign_id"] == cid for r in rows)
    assert {r["bar_type"] for r in rows} == {
        "time", "volume", "dollar", "volume_imbalance"}


# ===========================================================================
# 3. Exploration quota remains enforced
# ===========================================================================

def _approved_idea(db, idea_id, *, signal, cid, market="India",
                   universe="NIFTY50", bar_type="time"):
    """Insert an approved, campaign-tagged pending idea directly."""
    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO pending_ideas (idea_id, hypothesis, suggested_signals, "
            "source_model, market, universe, bar_type, status, validation_ok, "
            "campaign_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (idea_id, f"h_{signal}", f'["{signal}"]', "m", market, universe,
             bar_type, "approved", 1, cid),
        )
        conn.commit()


def _well_sampled(db, signal, *, market="India", universe="NIFTY50",
                  bar_type="time", n=3):
    """Make a signal's context cell well-sampled so EIG drops -> exploit bucket."""
    for i in range(n):
        eid = f"seed_{signal}_{i}"
        ledger_store.upsert_experiment(
            {"experiment_id": eid, "market": market, "universe": universe,
             "status": "completed", "bar_type": bar_type, "net_sharpe": 1.0},
            db_path=db)
        context_store.add_context_observation(
            experiment_id=eid, feature_name=signal, market=market,
            universe=universe, bar_type=bar_type, net_sharpe=1.0, kept=1,
            db_path=db)
    context_store.rebuild_context_cache(db, min_n=1)


def test_exploration_quota_remains_enforced(db):
    cid = _create_campaign(db)
    # Three EXPLOIT ideas (well-sampled, distinct contexts) + three EXPLORE ideas
    # (fresh signals). With a small dispatch window the high-value exploit ideas
    # must NOT consume every slot — the quota reserves explore capacity.
    for i, sig in enumerate(("ex_a", "ex_b", "ex_c")):
        _well_sampled(db, sig, universe=f"U{i}")
        _approved_idea(db, f"exploit{i}", signal=sig, cid=cid, universe=f"U{i}")
    for i, sig in enumerate(("fresh_a", "fresh_b", "fresh_c")):
        _approved_idea(db, f"explore{i}", signal=sig, cid=cid, universe=f"V{i}")

    sched = ResearchScheduler(db, config=SchedulerConfig())
    plan = sched.dispatch(limit=3)
    buckets = [d.bucket for d in plan]
    assert "explore" in buckets, "exploration quota must reserve an explore slot"
    assert buckets.count("exploit") < len(plan), "exploit cannot take all slots"

    # Accounting reconstructed from the scheduler log matches the reporter.
    stats = sched.exploration_stats(campaign_id=cid)
    report = exploration_summary(cid, db_path=db)
    assert report.explore == stats["explore"]
    assert report.exploit == stats["exploit"]
    assert report.total == stats["total"] == len(plan)


# ===========================================================================
# 4. Frontier expansion obeys limits
# ===========================================================================

def test_frontier_expansion_obeys_limits(db):
    # A single-market, single-bar scope with a max_children_per_frontier cap:
    # the root may spawn at most `cap` children even across many ticks.
    cid = _create_campaign(db, scope={
        "markets": ["India"], "universes": ["NIFTY50"],
        "bar_types": ["time", "volume", "dollar", "volume_imbalance",
                      "tick", "dollar_imbalance"],
    })
    cap = 2
    strat = ResearchStrategist(
        db_path=db, config=StrategistConfig(min_n=1, max_children_per_frontier=cap))
    seed = strat.seed(cid, "momentum time", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")
    _confirm_node(db, strat, seed.node_id)

    # Repeatedly try to expand the SAME root frontier.
    for _ in range(5):
        proposals = strat.propose(cid)
        if not proposals:
            break
        res = strat.apply(cid, proposals)
        for r in res:
            # do not confirm children, so the only expandable node stays the root
            pass

    children = hypothesis_store.children_of(seed.node_id, db_path=db)
    assert len({e["child_id"] for e in children}) <= cap
    # Once the root has hit the cap it is retired from the frontier.
    assert strat.propose(cid) == []


# ===========================================================================
# 5. Campaign budget accounting is correct
# ===========================================================================

def test_campaign_budget_accounting_is_correct(db):
    cid = _create_campaign(db, budget=2)
    cm = CampaignManager(db_path=db)
    strat = ResearchStrategist(db_path=db, config=_CFG)
    seed = strat.seed(cid, "momentum time", signals=["mom_20"],
                      market="India", universe="NIFTY50", bar_type="time")

    assert cm.budget_exhausted(cid) is False
    # Two attributed experiments == budget of 2 -> exhausted.
    _confirm_node(db, strat, seed.node_id)            # 1 experiment
    p = strat.propose(cid)
    res = strat.apply(cid, p)
    _confirm_node(db, strat, res[0].node_id)          # 2 experiments
    cm.reconcile(cid)

    camp = campaign_store.get_campaign(cid, db_path=db)
    assert camp["budget_spent"] == 2
    assert cm.budget_exhausted(cid) is True
    # An exhausted campaign yields no further strategist moves.
    assert strat.propose(cid) == []

    ov = campaign_overview_summary(cid, db_path=db)
    assert ov.n_experiments == 2
    assert ov.budget_experiments == 2 and ov.budget_spent == 2


# ===========================================================================
# 6. Recovery / checkpoint logic survives campaign execution (real M7 loop)
# ===========================================================================

def _seed_and_approve(db, cid, *, signals=("mr_ret_5",), market="us",
                      universe="test_universe"):
    strat = ResearchStrategist(db_path=db)
    res = strat.seed(cid, "reversal works", signals=list(signals),
                     market=market, universe=universe)
    assert q.approve_idea(res.idea_id, db_path=db) is True
    return res.idea_id


def _loop(db, completed_dir, data_root, **cfg):
    return ResearchLoop(
        db, config=LoopConfig(generate=False, **cfg),
        data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider,
    )


def test_recovery_checkpoint_survives_campaign_execution(
        db, completed_dir, data_root, monkeypatch):
    cid = _create_campaign(db)
    idea_id = _seed_and_approve(db, cid)
    loop = _loop(db, completed_dir, data_root)

    # Crash the real executor mid-dispatch, AFTER schedule has committed events.
    def _boom(*a, **k):
        raise RuntimeError("crash before execution")
    monkeypatch.setattr(idea_executor, "run_single_approved_idea", _boom)
    with pytest.raises(RuntimeError):
        loop.run_tick(cid)

    tick_id = f"{cid}#t0001"
    assert loop_store.phase_completed(tick_id, loop_store.PHASE_SCHEDULE, db_path=db)
    assert not loop_store.phase_completed(tick_id, loop_store.PHASE_DISPATCH, db_path=db)
    assert idea_id in scheduler_store.in_flight_idea_ids(db_path=db)

    # Restart: the SAME tick resumes; schedule is skipped (no duplicate dispatch),
    # the real executor runs, and the experiment lands in the ledger exactly once.
    monkeypatch.undo()
    report = loop.run_tick(cid)
    assert report.resumed is True and report.tick_id == tick_id
    assert report.phase("schedule").ran is False
    assert report.phase("dispatch").ran is True
    assert q.get_idea(idea_id, db_path=db)["status"] == "executed"
    assert len(ledger_store.list_experiments(db_path=db)) == 1
    assert loop_store.tick_completed(tick_id, db_path=db)


def test_full_loop_executes_real_experiment_end_to_end(
        db, completed_dir, data_root):
    cid = _create_campaign(db)
    idea_id = _seed_and_approve(db, cid)
    report = _loop(db, completed_dir, data_root).run_tick(cid)

    assert loop_store.tick_completed(report.tick_id, db_path=db)
    assert report.phase("dispatch").evidence["executed"] == [idea_id]
    assert q.get_idea(idea_id, db_path=db)["status"] == "executed"
    assert len(ledger_store.list_experiments(db_path=db)) == 1
    actions = [e["action"] for e in scheduler_store.list_events(idea_id=idea_id, db_path=db)]
    assert scheduler_store.ACTION_DISPATCHED in actions
    assert scheduler_store.ACTION_SUCCEEDED in actions
    # The human gate held: the idea was approved by a human, never auto-approved.
    assert q.list_by_status("pending", db_path=db) == []


# ===========================================================================
# 7. CampaignReporter renders expected outputs
# ===========================================================================

def test_campaign_reporter_renders_expected_outputs(db):
    cid = _create_campaign(db)
    _walk_altbars(db, cid)

    # Overview reflects the worked walk (5 nodes: seed + 4 generations).
    ov = campaign_overview_summary(cid, db_path=db)
    assert ov.state == STATE_ACTIVE
    assert ov.n_hypotheses == 5
    assert ov.n_experiments == 5

    # Ranking includes the campaign; it is the only/most productive one.
    ranking = campaign_ranking_summary(db_path=db)
    assert ranking[0].campaign_id == cid and ranking[0].rank == 1

    # No stalled campaigns yet.
    assert stalled_campaign_summary(db_path=db) == []

    # Productive contexts cover all four bar types from the walk.
    contexts = productive_context_summary(top=20, db_path=db)
    assert {c.bar_type for c in contexts} >= {
        "time", "volume", "dollar", "volume_imbalance"}

    # Hypothesis tree renders the full lineage from stored nodes/edges.
    forest = hypothesis_tree_summary(cid, db_path=db)
    assert len(forest) == 1
    root = forest[0]
    assert root.depth == 0
    # The deepest path reaches generation 4 (cross-market child).
    def max_depth(node):
        return max([node.depth] + [max_depth(c) for c in node.children])
    assert max_depth(root) == 4

    # Markdown board renders all sections + the campaign theme.
    md = generate_campaign_report(cid, db_path=db)
    for heading in ("# Campaign Report", "## Campaign Overview",
                    "## Campaign Ranking", "## Exploration vs Exploitation",
                    "## Productive Contexts", "## Hypothesis Evolution Tree"):
        assert heading in md
    assert "Alternative Bars" in md


def test_reporter_shows_stalled_campaign(db):
    cid = _create_campaign(db)
    CampaignManager(db_path=db).mark_stalled(cid)
    stalled = stalled_campaign_summary(db_path=db)
    assert [s.campaign_id for s in stalled] == [cid]
    ov = campaign_overview_summary(cid, db_path=db)
    assert ov.state == STATE_STALLED


# ===========================================================================
# 8. Deterministic replay produces identical results
# ===========================================================================

def _replay_signature(db, cid):
    """A storage-derived fingerprint of the worked campaign: the ordered
    hypothesis-tree shape + the reporter overview + exploration accounting."""
    nodes = hypothesis_store.list_nodes(cid, db_path=db)
    tree_sig = tuple(
        (n["depth"], n["origin_operator"], n["bar_type"], n["market"],
         n["universe"]) for n in nodes
    )
    edges = hypothesis_store.list_edges(cid, db_path=db)
    edge_sig = tuple((e["operator"],) for e in edges)
    ov = campaign_overview_summary(cid, db_path=db)
    return (tree_sig, edge_sig, ov.n_hypotheses, ov.n_experiments, ov.state)


def test_deterministic_replay_produces_identical_results(tmp_path):
    sigs = []
    for run in range(2):
        path = tmp_path / f"replay_{run}.db"
        create_all_tables(path)
        cid = _create_campaign(path, cid="altbars")
        _walk_altbars(path, cid)
        sigs.append(_replay_signature(path, cid))
    # Two independent builds of the same campaign produce identical state.
    assert sigs[0] == sigs[1]
