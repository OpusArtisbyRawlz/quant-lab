"""
M10 bug-fix regression — node<->experiment back-link in the research loop.

Bug discovered during the real Alternative Bars campaign: the production loop
executed ideas and stamped the idea<->experiment link in the approval queue, but
never propagated that experiment back onto the originating *hypothesis node*.
Because the strategist's frontier checks (``_expandable`` / ``_confirmed`` /
``_refuted``) all gate on ``node.experiment_id``, every real campaign halted at
its seed — the tree could never evolve past generation 0.

These tests drive the *real* M7 executor through the loop (synthetic data, no
network) and prove the loop now stamps the node, that the strategist sees the
executed experiment, that campaigns evolve beyond generation 0 when the evidence
permits, and that deterministic replay is unaffected.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.storage.db import create_all_tables
from agents.storage import hypothesis_store, ledger_store, context_store
from agents.campaign_manager import CampaignManager
from agents.research_strategist import ResearchStrategist, StrategistConfig
from agents.research_scheduler import SchedulerConfig
from agents.research_loop import ResearchLoop, LoopConfig
from agents.idea_generator import approval_queue as q


# ---------------------------------------------------------------------------
# Fixtures (mirror test_altbars_campaign.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "linkage.db"
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


SCOPE = {
    "markets": ["us", "india"],
    "universes": ["test_universe", "nifty"],
    "bar_types": ["time", "volume", "dollar"],
}
_CFG = StrategistConfig(min_n=1)


def _create_campaign(db, cid="link", *, budget=0, scope=None):
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, "Linkage", goal_spec={"priority": 0.7},
                       scope=scope or SCOPE, budget_experiments=budget)
    cm.activate(cid, reason_code="kickoff")
    return cid


def _loop(db, completed_dir, data_root, *, generate=False, strategist=None):
    return ResearchLoop(
        db,
        config=LoopConfig(generate=generate,
                          scheduler_config=SchedulerConfig(exploration_fraction=0.34)),
        strategist=strategist,
        data_root=data_root, completed_dir=completed_dir,
        data_dict_provider=_provider,
    )


def _approve_pending(db, cid):
    n = 0
    for idea in q.list_by_status("pending", db_path=db):
        if idea.get("campaign_id") == cid and q.approve_idea(idea["idea_id"], db_path=db):
            n += 1
    return n


# ===========================================================================
# 1. The seed node receives its experiment_id after the loop executes it
# ===========================================================================

def test_seed_node_receives_experiment_id(db, completed_dir, data_root):
    cid = _create_campaign(db)
    strat = ResearchStrategist(db_path=db, config=_CFG)
    seed = strat.seed(cid, "reversal works", signals=["mr_ret_5"],
                      market="us", universe="test_universe", bar_type="time")
    assert q.approve_idea(seed.idea_id, db_path=db) is True

    # Before dispatch the node carries no experiment.
    node = hypothesis_store.get_node(seed.node_id, db_path=db)
    assert node["experiment_id"] is None

    report = _loop(db, completed_dir, data_root).run_tick(cid)
    assert report.phase("dispatch").evidence["executed"] == [seed.idea_id]

    # The loop stamped the executed experiment back onto the seed node.
    node = hypothesis_store.get_node(seed.node_id, db_path=db)
    assert node["experiment_id"] is not None
    exps = ledger_store.list_experiments(db_path=db)
    assert len(exps) == 1
    assert node["experiment_id"] == exps[0]["experiment_id"]
    # And it matches the idea<->experiment link in the approval queue.
    assert node["experiment_id"] == q.get_idea(seed.idea_id, db_path=db)["experiment_id"]


# ===========================================================================
# 2. The strategist's frontier checks now see the executed experiment
# ===========================================================================

def test_frontier_checks_see_executed_experiment(db, completed_dir, data_root):
    cid = _create_campaign(db)
    strat = ResearchStrategist(db_path=db, config=_CFG)
    seed = strat.seed(cid, "reversal works", signals=["mr_ret_5"],
                      market="us", universe="test_universe", bar_type="time")
    assert q.approve_idea(seed.idea_id, db_path=db) is True
    _loop(db, completed_dir, data_root).run_tick(cid)

    node = hypothesis_store.get_node(seed.node_id, db_path=db)
    # _expandable depends solely on the experiment stamp (plus depth/operator).
    assert hypothesis_store.node_has_experiment(node) if hasattr(
        hypothesis_store, "node_has_experiment") else node["experiment_id"]
    assert strat._expandable(node) is True

    # M9 attribution ran inside the executor, so a context cell exists and the
    # node is classified as exactly one of confirmed / refuted (not "no data").
    cell = strat._cell("mr_ret_5", "us", "test_universe", "time")
    assert cell is not None and cell["n_experiments"] >= 1
    confirmed = strat._confirmed("mr_ret_5", "us", "test_universe", "time")
    refuted = strat._refuted("mr_ret_5", "us", "test_universe", "time")
    assert confirmed != refuted  # decisive classification, never both/neither


# ===========================================================================
# 3. Campaigns evolve beyond generation 0 once evidence exists
# ===========================================================================

def test_campaign_evolves_beyond_generation_zero(db, completed_dir, data_root):
    cid = _create_campaign(db)
    strat = ResearchStrategist(db_path=db, config=_CFG)
    seed = strat.seed(cid, "reversal works", signals=["mr_ret_5"],
                      market="us", universe="test_universe", bar_type="time")
    # Loop shares the min_n=1 strategist so generate uses the same evidence bar.
    loop = _loop(db, completed_dir, data_root, generate=True, strategist=strat)

    max_depth_seen = 0
    for _ in range(8):
        _approve_pending(db, cid)
        loop.run_tick(cid)
        nodes = hypothesis_store.list_nodes(cid, db_path=db)
        max_depth_seen = max((n["depth"] for n in nodes), default=0)
        if max_depth_seen >= 1:
            break

    nodes = hypothesis_store.list_nodes(cid, db_path=db)
    # The tree grew past the seed: at least one generation-1 (child) node exists,
    # and it was produced by a real strategist operator (not the seed).
    assert max_depth_seen >= 1, f"tree never evolved past gen 0: {nodes}"
    children = [n for n in nodes if n["depth"] >= 1]
    assert children, "no child hypothesis nodes were generated"
    assert all(c["origin_operator"] is not None for c in children)


# ===========================================================================
# 4. Deterministic replay still passes with the back-link in place
# ===========================================================================

def _run_campaign(db, completed_dir, data_root):
    cid = _create_campaign(db)
    strat = ResearchStrategist(db_path=db, config=_CFG)
    strat.seed(cid, "reversal works", signals=["mr_ret_5"],
               market="us", universe="test_universe", bar_type="time")
    loop = _loop(db, completed_dir, data_root, generate=True, strategist=strat)
    for _ in range(6):
        _approve_pending(db, cid)
        loop.run_tick(cid)
    nodes = hypothesis_store.list_nodes(cid, db_path=db)
    return tuple(
        (n["depth"], n["origin_operator"], n["bar_type"],
         n["market"], n["universe"], n["experiment_id"] is not None)
        for n in nodes
    )


def test_deterministic_replay(tmp_path):
    sig = []
    for run in range(2):
        d = tmp_path / f"run{run}"
        d.mkdir()
        db = d / "replay.db"
        create_all_tables(db)
        completed = d / "completed"; completed.mkdir()
        raw = d / "raw"; raw.mkdir()
        sig.append(_run_campaign(db, completed, raw))
    assert sig[0] == sig[1], f"replay diverged:\n{sig[0]}\n{sig[1]}"
    # Replay is non-trivial: the seed at minimum executed and was stamped.
    assert sig[0] and sig[0][0][5] is True
