"""
M10 PR-11 — Final boundary guards & architectural validation.

This module *seals* Milestone 10. It does not add behaviour; it pins the
architectural contract so future work cannot silently regress an M10 invariant
or pull an M11 responsibility into the M10 stack. The guards are deliberately a
mix of two complementary techniques:

  * **Static (AST) guards** — parse the source of the M10 control modules and
    assert structural facts that no amount of runtime seeding could prove:
    e.g. the strategist *cannot* execute experiments because it never imports
    the executor; only the loop imports M7; nothing in M10 calls the M9 signal
    writers or the human-gate approval mutator.

  * **Behavioural guards** — drive the real components and assert the runtime
    contract: a pending (un-approved) idea is never dispatched (the human gate
    is not bypassable), the CampaignReporter changes no row counts, and a
    deterministic replay of the worked walk produces an identical fingerprint.

The M10 ⇄ M11 boundary
----------------------
M10 is the *autonomous research loop*: it proposes hypotheses, schedules and
dispatches **human-approved** ideas through the unchanged M7 executor, lets M9
learn, and reports read-only. M10 deliberately does **not**:

  * certify statistical significance of a result,
  * claim a strategy is deployment / production ready,
  * auto-approve ideas or otherwise bypass the human approval queue,
  * execute experiments itself (only M7 does),
  * mutate signal intelligence itself (only M9 does).

Those are M11 (and beyond) responsibilities; see the deferral list at the
bottom of this file and ``docs/ROADMAP.md``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.campaign_manager import CampaignManager
from agents.campaign_manager.manager import STATE_ACTIVE
from agents.research_strategist import ResearchStrategist, StrategistConfig
from agents.research_scheduler import ResearchScheduler, SchedulerConfig
from agents.research_loop import ResearchLoop, LoopConfig
from agents.idea_generator import approval_queue as q
from agents.idea_generator import idea_executor
from agents.storage import (
    hypothesis_store,
    context_store,
    ledger_store,
    scheduler_store,
)
from agents.reporting import (
    campaign_overview_summary,
    campaign_ranking_summary,
    stalled_campaign_summary,
    exploration_summary,
    productive_context_summary,
    recent_knowledge_summary,
    signal_lifecycle_board_summary,
    hypothesis_tree_summary,
    generate_campaign_report,
)


# ---------------------------------------------------------------------------
# Source locations of the M10 stack
# ---------------------------------------------------------------------------

_AGENTS = Path(__file__).parent.parent

# The M10 *control* modules (orchestration / proposal / scheduling / state).
STRATEGIST_SRC = _AGENTS / "research_strategist" / "strategist.py"
SCHEDULER_SRC = _AGENTS / "research_scheduler" / "scheduler.py"
LOOP_SRC = _AGENTS / "research_loop" / "loop.py"
CAMPAIGN_SRC = _AGENTS / "campaign_manager" / "manager.py"

# All M10 control modules that must never execute or learn on their own.
M10_CONTROL = (STRATEGIST_SRC, SCHEDULER_SRC, CAMPAIGN_SRC)

# The read-only reporting package (M10's reporting surface).
REPORTING_PKG = _AGENTS / "reporting"

# M7 execution modules — only the loop may import these.
EXECUTION_MODULES = ("idea_executor", "experiment_runner", "cycle_runner")

# M9 signal-intelligence writers — only M9 may call these.
SIGNAL_WRITERS = (
    "upsert_signal", "add_experiment_to_signal", "update_signal_status",
    "update_lifecycle", "log_lifecycle_event",
)

# The human-gate mutator — nothing in M10 may auto-approve.
APPROVE_FN = "approve_idea"


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imported_modules(path: Path) -> set[str]:
    """All module paths AND imported names referenced by a file. Captures both
    ``import x.y`` (module path) and ``from x.y import name`` (module path *and*
    each imported ``name``) so a ``from pkg import idea_executor`` is detected."""
    mods: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def _called_attrs(path: Path) -> set[str]:
    """Attribute names appearing in call positions, e.g. ``foo.bar()`` -> 'bar',
    plus bare ``bar()`` -> 'bar'. Used to detect forbidden API calls regardless
    of the import alias the module happens to use."""
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                names.add(fn.attr)
            elif isinstance(fn, ast.Name):
                names.add(fn.id)
    return names


def _func_defs(path: Path) -> set[str]:
    return {
        n.name
        for n in ast.walk(_tree(path))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# ===========================================================================
# 1. Execution-path integrity — Strategist / Scheduler cannot execute
# ===========================================================================

def test_strategist_cannot_execute_experiments():
    """Static proof: the strategist never imports any M7 execution module, so
    it structurally cannot run an experiment — it can only enqueue pending
    ideas for the human gate."""
    imports = _imported_modules(STRATEGIST_SRC)
    leaked = [m for m in imports if any(e in m for e in EXECUTION_MODULES)]
    assert leaked == [], f"strategist imports execution modules: {leaked}"


def test_scheduler_cannot_execute_experiments():
    """Static proof: the scheduler ranks and records dispatch *decisions* but
    never imports an executor — dispatch is a logged decision, not execution."""
    imports = _imported_modules(SCHEDULER_SRC)
    leaked = [m for m in imports if any(e in m for e in EXECUTION_MODULES)]
    assert leaked == [], f"scheduler imports execution modules: {leaked}"


def test_only_m7_executes_experiments():
    """Across the whole M10 stack, the *only* module permitted to import the M7
    executor is the research loop's dispatch phase. The strategist, scheduler,
    campaign manager and reporting package must all be executor-free."""
    must_be_clean = M10_CONTROL + tuple(REPORTING_PKG.glob("*.py"))
    for path in must_be_clean:
        leaked = [m for m in _imported_modules(path)
                  if any(e in m for e in EXECUTION_MODULES)]
        assert leaked == [], f"{path.name} imports execution module(s): {leaked}"
    # Positive: the loop *does* delegate to the unchanged M7 executor.
    assert any("idea_executor" in m for m in _imported_modules(LOOP_SRC)), \
        "the loop must dispatch through the M7 idea_executor"


# ===========================================================================
# 2. Learning-path integrity — only M9 updates signal intelligence
# ===========================================================================

def test_m10_does_not_mutate_signal_intelligence():
    """No M10 control module may call an M9 signal-intelligence writer. Signal
    lifecycle/intelligence is owned by M9 and happens inside the executor's
    learning step — never from the strategist/scheduler/loop/campaign manager."""
    for path in M10_CONTROL + (LOOP_SRC,):
        calls = _called_attrs(path)
        leaked = sorted(calls & set(SIGNAL_WRITERS))
        assert leaked == [], f"{path.name} calls M9 signal writer(s): {leaked}"


# ===========================================================================
# 3. Human approval gate — M10 cannot auto-approve / bypass the queue
# ===========================================================================

def test_m10_does_not_auto_approve_statically():
    """Static proof: nothing in the M10 stack calls the approval mutator. The
    only legitimate caller of ``approve_idea`` is a human action / its test."""
    for path in M10_CONTROL + (LOOP_SRC,):
        assert APPROVE_FN not in _called_attrs(path), \
            f"{path.name} calls {APPROVE_FN!r} — M10 must not auto-approve"


def _provider(spec):
    rng = np.random.default_rng(42)
    dates = pd.date_range("2020-01-02", periods=80, freq="B")
    out = {}
    for i in range(8):
        prices = 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, 80))
        df = pd.DataFrame({
            "Open": prices, "High": prices * 1.01, "Low": prices * 0.99,
            "Close": prices,
            "Volume": rng.integers(500_000, 2_000_000, 80).astype(float),
        }, index=dates)
        df.index.name = "Date"
        out[f"T{i:02d}"] = df
    return out


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "guards.db"
    create_all_tables(path)
    return path


@pytest.fixture
def io_dirs(tmp_path):
    raw = tmp_path / "raw"
    done = tmp_path / "completed"
    raw.mkdir()
    done.mkdir()
    return raw, done


def _campaign(db, cid="guard"):
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, "Guard", goal_spec={"priority": 0.5},
                       scope={"markets": ["us"], "universes": ["test_universe"],
                              "bar_types": ["time"]},
                       budget_experiments=0)
    cm.activate(cid, reason_code="kickoff")
    return cid


def test_human_gate_cannot_be_bypassed_at_runtime(db):
    """Behavioural proof: an enqueued-but-unapproved (pending) idea is never
    selected for dispatch — the scheduler draws only from the approved pool.
    A second, human-approved idea *is* dispatched, proving the gate is the only
    path to execution."""
    cid = _campaign(db)
    strat = ResearchStrategist(db_path=db)
    pending = strat.seed(cid, "pending idea", signals=["mom_20"],
                         market="us", universe="test_universe")
    # A separate approved idea so the dispatch pool is non-empty.
    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO pending_ideas (idea_id, hypothesis, suggested_signals, "
            "source_model, market, universe, bar_type, status, validation_ok, "
            "campaign_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("approved1", "approved idea", '["mr_ret_5"]', "m", "us",
             "test_universe", "time", "approved", 1, cid))
        conn.commit()

    plan = ResearchScheduler(db, config=SchedulerConfig()).dispatch(limit=5)
    dispatched = {d.idea_id for d in plan}
    assert pending.idea_id not in dispatched, \
        "a pending (un-approved) idea must never be dispatched"
    assert "approved1" in dispatched, "approved ideas must be dispatchable"
    # The pending idea is still pending — nothing auto-approved it.
    assert q.get_idea(pending.idea_id, db_path=db)["status"] == "pending"


def test_loop_dispatch_only_executes_approved_ideas(db, io_dirs):
    """End-to-end: the loop's dispatch phase runs the real M7 executor only for
    ideas the human approved. A pending idea present in the campaign is left
    untouched (never executed, never auto-approved)."""
    raw, done = io_dirs
    cid = _campaign(db)
    strat = ResearchStrategist(db_path=db)
    approved = strat.seed(cid, "approved", signals=["mr_ret_5"],
                          market="us", universe="test_universe")
    assert q.approve_idea(approved.idea_id, db_path=db) is True
    # A second, deliberately un-approved (pending) idea in the same campaign.
    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO pending_ideas (idea_id, hypothesis, suggested_signals, "
            "source_model, market, universe, bar_type, status, validation_ok, "
            "campaign_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("pending1", "left pending", '["mom_20"]', "m", "us",
             "test_universe", "time", "pending", 1, cid))
        conn.commit()
    pending_id = "pending1"

    loop = ResearchLoop(db, config=LoopConfig(generate=False),
                        data_root=raw, completed_dir=done,
                        data_dict_provider=_provider)
    report = loop.run_tick(cid)

    assert report.phase("dispatch").evidence["executed"] == [approved.idea_id]
    assert q.get_idea(approved.idea_id, db_path=db)["status"] == "executed"
    # The pending idea was never executed and never auto-approved.
    assert q.get_idea(pending_id, db_path=db)["status"] == "pending"
    assert len(ledger_store.list_experiments(db_path=db)) == 1


# ===========================================================================
# 4. M10 vs M11 responsibility guards — no significance / deployment / certify
# ===========================================================================

def test_m10_defines_no_significance_or_deployment_surface():
    """M10 must expose no API that certifies statistical significance, claims
    deployment/production readiness, or auto-approves. Guard the *public
    surface* (function/method names) of the whole M10 stack against those
    M11 concepts so the responsibility cannot creep in unnoticed."""
    banned_substrings = (
        "significan", "certif", "p_value", "pvalue",
        "deploy", "production_ready", "prod_ready", "go_live",
        "auto_approve", "autoapprove",
    )
    paths = M10_CONTROL + (LOOP_SRC,) + tuple(REPORTING_PKG.glob("*.py"))
    offenders: list[str] = []
    for path in paths:
        for name in _func_defs(path):
            low = name.lower()
            if any(b in low for b in banned_substrings):
                offenders.append(f"{path.name}:{name}")
    assert offenders == [], (
        "M10 exposes an M11-responsibility surface: " + ", ".join(offenders))


def test_reporter_makes_no_significance_or_readiness_claims(db):
    """The rendered campaign report describes *what happened* (counts, lineage,
    exploration accounting) but must never assert significance or readiness —
    those words must not appear as claims in the M10 reporting output."""
    cid = _campaign(db)
    strat = ResearchStrategist(db_path=db, config=StrategistConfig(min_n=1))
    seed = strat.seed(cid, "momentum", signals=["mom_20"],
                      market="us", universe="test_universe", bar_type="time")
    # Stamp a confirmed experiment so the report has real content to render.
    eid = "exp_seed"
    ledger_store.upsert_experiment(
        {"experiment_id": eid, "hypothesis": "momentum", "market": "us",
         "universe": "test_universe", "status": "completed", "bar_type": "time",
         "net_sharpe": 1.0}, db_path=db)
    with get_connection(db) as conn:
        conn.execute("UPDATE pending_ideas SET experiment_id=?, status='executed' "
                     "WHERE idea_id=?", (eid, seed.idea_id))
        conn.commit()
    md = generate_campaign_report(cid, db_path=db).lower()
    for claim in ("statistically significant", "deployment ready",
                  "production ready", "ready to deploy", "certified"):
        assert claim not in md, f"reporter must not claim {claim!r}"


# ===========================================================================
# 5. Read-only reporting validation — CampaignReporter performs no writes
# ===========================================================================

def test_campaign_reporter_performs_no_writes(db):
    """Every campaign-reporting entry point must leave every table's row count
    unchanged. (The package-level static no-write-SQL guard in test_reporting.py
    already globs these modules; this pins the *runtime* contract too.)"""
    cid = _campaign(db)
    strat = ResearchStrategist(db_path=db, config=StrategistConfig(min_n=1))
    seed = strat.seed(cid, "momentum", signals=["mom_20"],
                      market="us", universe="test_universe", bar_type="time")
    eid = "exp_seed"
    ledger_store.upsert_experiment(
        {"experiment_id": eid, "hypothesis": "momentum", "market": "us",
         "universe": "test_universe", "status": "completed", "bar_type": "time",
         "net_sharpe": 1.0}, db_path=db)
    strat.tree.link_experiment(seed.node_id, eid)
    with get_connection(db) as conn:
        conn.execute("UPDATE pending_ideas SET experiment_id=?, status='executed' "
                     "WHERE idea_id=?", (eid, seed.idea_id))
        conn.commit()
    scheduler_store.append_event(seed.idea_id, scheduler_store.ACTION_DISPATCHED,
                                 campaign_id=cid, evidence={"bucket": "explore"},
                                 db_path=db)

    tables = ("research_campaign", "campaign_state_events", "pending_ideas",
              "experiments", "scheduler_event", "hypothesis_node",
              "hypothesis_edge", "lessons_learned", "signal_library",
              "signal_context_observation", "loop_checkpoint")

    def snapshot():
        with get_connection(db) as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in tables}

    before = snapshot()
    campaign_overview_summary(db_path=db)
    campaign_overview_summary(cid, db_path=db)
    campaign_ranking_summary(db_path=db)
    stalled_campaign_summary(db_path=db)
    exploration_summary(db_path=db)
    exploration_summary(cid, db_path=db)
    productive_context_summary(db_path=db)
    recent_knowledge_summary(db_path=db)
    signal_lifecycle_board_summary(db_path=db)
    hypothesis_tree_summary(cid, db_path=db)
    generate_campaign_report(cid, db_path=db)
    generate_campaign_report(db_path=db)
    assert snapshot() == before


# ===========================================================================
# 6. Deterministic replay validation — stable across independent rebuilds
# ===========================================================================

def _walk(db, cid):
    """A short deterministic strategist walk: seed -> confirm -> vary-bar."""
    cfg = StrategistConfig(min_n=1)
    strat = ResearchStrategist(db_path=db, config=cfg)
    seed = strat.seed(cid, "momentum", signals=["mom_20"],
                      market="us", universe="test_universe", bar_type="time")

    def confirm(node_id):
        node = hypothesis_store.get_node(node_id, db_path=db)
        eid = f"exp_{node_id}"
        ledger_store.upsert_experiment(
            {"experiment_id": eid, "hypothesis": node["hypothesis"],
             "market": node["market"], "universe": node["universe"],
             "status": "completed", "bar_type": node["bar_type"],
             "net_sharpe": 1.0}, db_path=db)
        strat.tree.link_experiment(node_id, eid)
        if node.get("idea_id"):
            with get_connection(db) as conn:
                conn.execute("UPDATE pending_ideas SET experiment_id=?, "
                             "status='executed' WHERE idea_id=?",
                             (eid, node["idea_id"]))
                conn.commit()
        context_store.add_context_observation(
            experiment_id=eid, feature_name="mom_20", market=node["market"],
            universe=node["universe"], bar_type=node["bar_type"],
            net_sharpe=1.0, kept=1, db_path=db)
        context_store.rebuild_context_cache(db, min_n=1)

    confirm(seed.node_id)
    for _ in range(2):
        proposals = strat.propose(cid)
        if not proposals:
            break
        res = strat.apply(cid, proposals)
        confirm(res[0].node_id)


def _signature(db, cid):
    nodes = hypothesis_store.list_nodes(cid, db_path=db)
    tree = tuple((n["depth"], n["origin_operator"], n["bar_type"],
                  n["market"], n["universe"]) for n in nodes)
    edges = tuple((e["operator"],) for e in hypothesis_store.list_edges(cid, db_path=db))
    ov = campaign_overview_summary(cid, db_path=db)
    return (tree, edges, ov.n_hypotheses, ov.n_experiments, ov.state)


def test_deterministic_replay_remains_stable(tmp_path):
    """Two independent rebuilds of the same walk on fresh databases must yield
    byte-identical storage-derived fingerprints — the M10 architecture stays
    deterministic and reconstructible-from-storage."""
    sigs = []
    for run in range(2):
        path = tmp_path / f"replay_{run}.db"
        create_all_tables(path)
        cm = CampaignManager(db_path=path)
        cm.create_campaign("guard", "Guard", goal_spec={"priority": 0.5},
                           scope={"markets": ["us"],
                                  "universes": ["test_universe"],
                                  "bar_types": ["time", "volume", "dollar"]},
                           budget_experiments=0)
        cm.activate("guard", reason_code="kickoff")
        _walk(path, "guard")
        sigs.append(_signature(path, "guard"))
    assert sigs[0] == sigs[1]
    # And the campaign genuinely progressed (guards a vacuous all-empty match).
    assert sigs[0][2] >= 2 and sigs[0][4] == STATE_ACTIVE
