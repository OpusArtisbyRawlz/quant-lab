"""
Tests for the read-only M8 reporting package (agents/reporting/).

Covers the programmatic summary API, markdown rendering, the assembled report,
JSON-array unnesting (robustness_flags / validation_reasons), NULL net-metric
handling, source_model provenance filtering, and the read-only architecture
guarantee (no writes, no execution-module imports).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agents.storage.db import create_all_tables, get_connection
from agents.storage.ledger_store import upsert_experiment
from agents.storage.lessons_store import add_lesson
from agents.idea_generator import approval_queue as q
from agents.protocol import ProposedIdea

from agents.reporting import (
    source_model_summary,
    market_summary,
    universe_summary,
    combo_summary,
    idea_funnel_summary,
    rejection_reason_summary,
    critic_decision_summary,
    lesson_summary,
    robustness_summary,
    net_sharpe_distribution,
    research_overview,
    generate_research_report,
    write_research_report,
)
from agents.reporting import report_store as rs
from agents.reporting import markdown as md


# ---------------------------------------------------------------------------
# Fixtures / seeding
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "report.db"
    create_all_tables(path)
    return path


def _exp(db, exp_id, *, source_model=None, source_idea_id=None,
         market="us", universe="sp500", net_sharpe=None, net_calmar=None,
         decision=None, robustness_flags=None):
    rec = {
        "experiment_id": exp_id,
        "market": market,
        "universe": universe,
        "experiment_type": "portfolio",
        "status": "completed",
    }
    if source_model is not None:
        rec["source_model"] = source_model
    if source_idea_id is not None:
        rec["source_idea_id"] = source_idea_id
    if net_sharpe is not None:
        rec["net_sharpe"] = net_sharpe
    if net_calmar is not None:
        rec["net_calmar"] = net_calmar
    if decision is not None:
        rec["decision"] = decision
    if robustness_flags is not None:
        rec["robustness_flags"] = robustness_flags  # list -> JSON via _coerce
    upsert_experiment(rec, db_path=db)


def _idea(h="hypo", market="us", universe="sp500"):
    return ProposedIdea(
        hypothesis=h,
        suggested_signals=("mom_ret_5",),
        source_model="fake-llm",
        rationale="because",
        scores={"novelty_score": 0.5},
        market=market,
        universe=universe,
    )


@pytest.fixture
def seeded(db):
    # Idea-originated experiments (have source_model + source_idea_id).
    _exp(db, "exp_001", source_model="gpt-x", source_idea_id="idea_001",
         market="us", universe="sp500", net_sharpe=1.2, net_calmar=0.8,
         decision="keep", robustness_flags=["subperiod_unstable"])
    _exp(db, "exp_002", source_model="gpt-x", source_idea_id="idea_002",
         market="us", universe="sp500", net_sharpe=0.4, net_calmar=0.2,
         decision="reject", robustness_flags=["subperiod_unstable", "cost_sensitive"])
    _exp(db, "exp_003", source_model="claude-y", source_idea_id="idea_003",
         market="eu", universe="stoxx600", net_sharpe=1.8, net_calmar=1.1,
         decision="retest", robustness_flags=[])
    # Non-idea experiment: source_model NULL, must be excluded from model stats.
    _exp(db, "exp_legacy", market="us", universe="sp500", net_sharpe=0.9,
         decision="keep")
    # Idea experiment with NULL net metrics (pre-M5 style).
    _exp(db, "exp_004", source_model="claude-y", source_idea_id="idea_004",
         market="eu", universe="stoxx600", decision="keep")

    # Lessons.
    add_lesson("exp_001", "finding a", "impl", category="signal", db_path=db)
    add_lesson("exp_002", "finding b", "impl", category="overfitting", db_path=db)
    add_lesson("exp_003", "finding c", "impl", category="signal", db_path=db)

    # Ideas in various lifecycle states.
    for iid_h, status in [("a", "executed"), ("b", "executed"),
                          ("c", "approved"), ("d", "pending")]:
        idea = _idea(iid_h)
        iid = q.make_idea_id(idea, db_path=db)
        q.enqueue(idea, iid, db_path=db)
        if status == "executed":
            q.approve_idea(iid, db_path=db)
            q.claim_for_execution(iid, db_path=db)
            q.mark_executed(iid, f"exp_{iid_h}", db_path=db)
        elif status == "approved":
            q.approve_idea(iid, db_path=db)
    # Rejected-at-validation ideas with reasons.
    q.record_rejected(_idea("bad1"), q.make_idea_id(_idea("bad1"), db_path=db),
                      ["unknown_signal(s): ['x']"], db_path=db)
    q.record_rejected(_idea("bad2"), q.make_idea_id(_idea("bad2"), db_path=db),
                      ["unknown_signal(s): ['y']", "empty_hypothesis"], db_path=db)
    return db


# ---------------------------------------------------------------------------
# source_model
# ---------------------------------------------------------------------------

def test_source_model_summary_excludes_non_idea_experiments(seeded):
    stats = source_model_summary(db_path=seeded)
    models = {s.source_model for s in stats}
    assert models == {"gpt-x", "claude-y"}  # legacy (NULL model) excluded


def test_source_model_summary_net_average_skips_nulls(seeded):
    stats = {s.source_model: s for s in source_model_summary(db_path=seeded)}
    # claude-y has exp_003 (1.8) + exp_004 (NULL net) -> avg over 1 row.
    cy = stats["claude-y"]
    assert cy.n_experiments == 2
    assert cy.n_with_net == 1
    assert cy.avg_net_sharpe == 1.8
    gx = stats["gpt-x"]
    assert gx.n_experiments == 2 and gx.n_with_net == 2
    assert gx.avg_net_sharpe == pytest.approx(0.8)
    assert gx.keep_rate == 0.5


def test_source_model_summary_ordered_best_first(seeded):
    stats = source_model_summary(db_path=seeded)
    assert stats[0].source_model == "claude-y"  # 1.8 > 0.8


# ---------------------------------------------------------------------------
# market / universe / combo
# ---------------------------------------------------------------------------

def test_market_summary_includes_all_experiments(seeded):
    stats = {s.key: s for s in market_summary(db_path=seeded)}
    # us: exp_001, exp_002, exp_legacy = 3 ; eu: exp_003, exp_004 = 2
    assert stats["us"].n_experiments == 3
    assert stats["eu"].n_experiments == 2
    assert stats["eu"].n_with_net == 1  # exp_004 net NULL


def test_universe_summary_keys(seeded):
    keys = {s.key for s in universe_summary(db_path=seeded)}
    assert keys == {"sp500", "stoxx600"}


def test_combo_summary_groups_and_min_n(seeded):
    all_combos = combo_summary(db_path=seeded)
    # idea experiments only -> (us,sp500,gpt-x)=2, (eu,stoxx600,claude-y)=2
    triples = {(c.market, c.universe, c.source_model): c for c in all_combos}
    assert (("us", "sp500", "gpt-x")) in triples
    assert triples[("us", "sp500", "gpt-x")].n_experiments == 2
    # legacy experiment (no source_idea_id) excluded
    assert all("legacy" not in c.source_model for c in all_combos)
    # min_n filter
    assert combo_summary(db_path=seeded, min_n=3) == []


# ---------------------------------------------------------------------------
# funnel / rejection / critic
# ---------------------------------------------------------------------------

def test_idea_funnel_counts_and_rates(seeded):
    f = idea_funnel_summary(db_path=seeded)
    assert f.executed == 2
    assert f.approved == 1
    assert f.pending == 1
    assert f.rejected == 2
    assert f.total == 6
    assert f.execution_rate == pytest.approx(2 / 6, abs=1e-4)
    assert f.rejection_rate == pytest.approx(2 / 6, abs=1e-4)


def test_rejection_reason_summary_unnests_json(seeded):
    reasons = {c.label: c.count for c in rejection_reason_summary(db_path=seeded)}
    assert reasons["unknown_signal(s): ['x']"] == 1
    assert reasons["unknown_signal(s): ['y']"] == 1
    assert reasons["empty_hypothesis"] == 1


def test_critic_decision_summary_over_idea_experiments(seeded):
    d = critic_decision_summary(db_path=seeded)
    # idea experiments with decision: exp_001 keep, 002 reject, 003 retest, 004 keep
    assert d.total == 4
    assert d.keep == 2 and d.reject == 1 and d.retest == 1
    assert d.survival_rate == pytest.approx(3 / 4)


# ---------------------------------------------------------------------------
# lessons / robustness / distribution / overview
# ---------------------------------------------------------------------------

def test_lesson_summary_category_counts(seeded):
    cats = {c.label: c.count for c in lesson_summary(db_path=seeded)}
    assert cats["signal"] == 2
    assert cats["overfitting"] == 1
    # ordered most frequent first
    assert lesson_summary(db_path=seeded)[0].label == "signal"


def test_robustness_summary_unnests_and_counts(seeded):
    flags = {c.label: c.count for c in robustness_summary(db_path=seeded)}
    assert flags["subperiod_unstable"] == 2
    assert flags["cost_sensitive"] == 1


def test_net_sharpe_distribution_buckets(seeded):
    buckets = net_sharpe_distribution(db_path=seeded)
    total = sum(b.count for b in buckets)
    # experiments with non-NULL net_sharpe: 1.2, 0.4, 1.8, 0.9 = 4
    assert total == 4
    # 0.4 in [0,0.5); 0.9 in [0.5,1.0); 1.2 in [1.0,1.5); 1.8 in >=2.0? no -> [1.5,2.0)
    by_label = {(b.lower, b.upper): b.count for b in buckets}
    assert by_label[(0.0, 0.5)] == 1
    assert by_label[(0.5, 1.0)] == 1
    assert by_label[(1.0, 1.5)] == 1
    assert by_label[(1.5, 2.0)] == 1


def test_research_overview_counts(seeded):
    o = research_overview(db_path=seeded)
    assert o.total_experiments == 5
    assert o.idea_experiments == 4  # exp_legacy excluded
    assert o.total_lessons == 3
    assert o.n_with_net == 4


def test_empty_db_is_safe(db):
    assert source_model_summary(db_path=db) == []
    assert market_summary(db_path=db) == []
    f = idea_funnel_summary(db_path=db)
    assert f.total == 0 and f.approval_rate is None
    d = critic_decision_summary(db_path=db)
    assert d.total == 0 and d.keep_rate is None
    o = research_overview(db_path=db)
    assert o.total_experiments == 0 and o.avg_net_sharpe is None
    # report still renders without raising
    report = generate_research_report(db_path=db)
    assert "# Research Report" in report


# ---------------------------------------------------------------------------
# markdown / report
# ---------------------------------------------------------------------------

def test_markdown_handles_none_values():
    assert md._fmt(None) == "—"
    assert md._fmt(1.23456) == "1.235"
    assert md._pct(None) == "—"
    assert md._pct(0.5) == "50.0%"


def test_generate_research_report_has_all_sections(seeded):
    report = generate_research_report(db_path=seeded)
    for heading in [
        "# Research Report",
        "## Research Summary",
        "## Idea Funnel",
        "## Best Source Models",
        "## Best Markets",
        "## Best Universes",
        "## Best Market / Universe / Model Combinations",
        "## Critic Decisions",
        "## Net Sharpe Distribution",
        "## Common Rejection Reasons",
        "## Common Lesson Categories",
        "## Robustness Flags",
    ]:
        assert heading in report
    assert "gpt-x" in report and "claude-y" in report


def test_write_research_report_writes_file(seeded, tmp_path):
    out = tmp_path / "sub" / "research.md"
    written = write_research_report(out, db_path=seeded)
    assert written == out
    assert out.read_text(encoding="utf-8").startswith("# Research Report")


# ---------------------------------------------------------------------------
# Read-only architecture guarantees
# ---------------------------------------------------------------------------

def test_reporting_issues_no_writes(seeded):
    """Generating every report must not change any table's row counts."""
    def snapshot():
        with get_connection(seeded) as conn:
            return {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("experiments", "pending_ideas", "lessons_learned")
            }

    before = snapshot()
    source_model_summary(db_path=seeded)
    market_summary(db_path=seeded)
    universe_summary(db_path=seeded)
    combo_summary(db_path=seeded)
    idea_funnel_summary(db_path=seeded)
    rejection_reason_summary(db_path=seeded)
    critic_decision_summary(db_path=seeded)
    lesson_summary(db_path=seeded)
    robustness_summary(db_path=seeded)
    net_sharpe_distribution(db_path=seeded)
    research_overview(db_path=seeded)
    generate_research_report(db_path=seeded)
    assert snapshot() == before


def test_reporting_modules_contain_no_write_sql():
    """Static check: no mutating SQL keyword appears in the reporting package."""
    pkg = Path(__file__).parent.parent / "reporting"
    # SQL-specific phrases (won't appear in explanatory prose the way bare
    # verbs like "UPDATE" might). Checks the actual query strings only.
    banned = ("INSERT INTO", "DELETE FROM", "UPDATE SET", "DROP TABLE",
              "ALTER TABLE", "CREATE TABLE")
    for py in pkg.glob("*.py"):
        # Inspect only string constants (the SQL lives there), skip comments/prose
        # by collecting Constant string nodes via AST.
        tree = ast.parse(py.read_text(encoding="utf-8"))
        sql_strings = [
            node.value.upper()
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and ("SELECT" in node.value.upper() or "FROM " in node.value.upper())
        ]
        for text in sql_strings:
            for kw in banned:
                assert kw not in text, f"{py.name} query contains mutating SQL {kw!r}"


def test_reporting_does_not_import_execution_modules():
    """Reporting must not import execution/agent-action modules (read-only)."""
    pkg = Path(__file__).parent.parent / "reporting"
    forbidden = ("idea_executor", "experiment_runner", "cycle_runner",
                 "ledger_agent", "critic")
    violations = []
    for py in pkg.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mod = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
            elif isinstance(node, ast.Import):
                mod = ",".join(a.name for a in node.names)
            for bad in forbidden:
                if bad in mod:
                    violations.append(f"{py.name}: imports {mod!r}")
    assert violations == [], "execution modules imported:\n" + "\n".join(violations)
