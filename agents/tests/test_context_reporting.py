"""Tests for the Milestone 9 reporting + IdeaGenerator consumption layers:
context_report_store, the report sections, and context_advisor."""

import json

from agents.reporting import context_report_store as crs
from agents.reporting import report
from agents.idea_generator.context_advisor import build_context_advice
from agents.idea_generator.prompt import build_prompt
from agents.signal_librarian.librarian import SignalLibrarian, LibrarianConfig
from agents.storage.ledger_store import upsert_experiment


def _exp(eid, *, features, market, universe, vol, net_sharpe, db_path):
    upsert_experiment({
        "experiment_id": eid, "status": "complete",
        "features": json.dumps(features), "market": market,
        "universe": universe, "vol": vol, "net_sharpe": net_sharpe,
        "net_calmar": net_sharpe, "decision": "keep",
    }, db_path=db_path)


def _seed_promoted(tmp_db):
    lib = SignalLibrarian(LibrarianConfig(min_n=1))
    _exp("E1", features=["mom20"], market="India", universe="NIFTY50",
         vol=0.4, net_sharpe=1.8, db_path=tmp_db)
    _exp("E2", features=["mom20"], market="US", universe="SP500",
         vol=0.1, net_sharpe=1.2, db_path=tmp_db)
    lib.record_experiment("E1", db_path=tmp_db)
    lib.record_experiment("E2", db_path=tmp_db)


def test_signal_context_summary_returns_cells(tmp_db):
    _seed_promoted(tmp_db)
    cells = crs.signal_context_summary(feature_name="mom20", db_path=tmp_db)
    assert len(cells) == 2
    assert {c.market for c in cells} == {"India", "US"}


def test_generalization_report_marks_promoted_first(tmp_db):
    _seed_promoted(tmp_db)
    rep = crs.signal_generalization_report(db_path=tmp_db)
    assert rep
    assert rep[0].lifecycle_state == "promoted"
    assert rep[0].distinct_markets == 2


def test_lifecycle_audit_report_lists_transitions(tmp_db):
    _seed_promoted(tmp_db)
    events = crs.lifecycle_audit_report(feature_name="mom20", db_path=tmp_db)
    assert any(e.to_state == "promoted" for e in events)


def test_report_includes_context_sections(tmp_db):
    _seed_promoted(tmp_db)
    md = report.generate_research_report(db_path=tmp_db)
    assert "Signal Generalization (context-aware)" in md
    assert "Signal Performance by Context" in md
    assert "Signal Lifecycle Events" in md
    assert "never aggregated globally" in md


# --------------------------------------------------------------------------- #
# context_advisor                                                             #
# --------------------------------------------------------------------------- #

def test_advisor_reserves_exploration_quota(tmp_db):
    adv = build_context_advice(
        ["mom20", "rev5", "vol10"], market="India", n=3, db_path=tmp_db)
    assert adv.explore_quota >= 1
    assert adv.exploration  # under-tested signals offered


def test_advisor_surfaces_generalizers(tmp_db):
    _seed_promoted(tmp_db)
    adv = build_context_advice(["mom20"], n=3, min_n=1, db_path=tmp_db)
    assert any(g.feature_name == "mom20" for g in adv.generalizers)


def test_advisor_targets_context(tmp_db):
    _seed_promoted(tmp_db)
    adv = build_context_advice(["mom20"], market="India", n=3, min_n=1,
                               db_path=tmp_db)
    assert any(t.feature_name == "mom20" for t in adv.targeted)


def test_prompt_renders_advice(tmp_db):
    adv = build_context_advice(["mom20", "rev5"], market="India", n=3,
                               db_path=tmp_db)
    p = build_prompt(["mom20", "rev5"], [], [], n=3, advice=adv)
    assert "Context-aware guidance" in p
    assert "exploration quota" in p


def test_prompt_without_advice_unchanged(tmp_db):
    p = build_prompt(["mom20"], [], [], n=3)
    assert "Context-aware guidance" not in p
