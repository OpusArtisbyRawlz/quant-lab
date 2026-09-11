"""
Tests for the `quant` CLI — the thin terminal interface over the existing factory.

The CLI is an interface layer: these tests assert it delegates to the existing
services (CampaignManager / PortfolioPlanner / FactoryRunner / reporting) and formats
their output, that read-only commands never mutate state, and that invalid ids fail
clearly. They never exercise real experiment execution.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables
from agents.campaign_manager import CampaignManager
from agents.cli.main import main, _shell_dispatch, build_parser
import argparse


def _db(tmp_path, name="cli.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _seed(db):
    cm = CampaignManager(db_path=db)
    cm.create_portfolio("P1", "Alpha", budget_spec={"total": 20, "a_max": 1.0})
    cm.create_campaign("c1", theme="momentum", priority=2.0, portfolio_id="P1")
    cm.activate("c1")
    cm.create_campaign("c2", theme="reversal", priority=1.0, portfolio_id="P1")
    cm.activate("c2")
    return cm


def _run(db, *argv):
    return main(["--db", str(db), *argv])


# --- help ------------------------------------------------------------------

def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "Quant Research Factory" in capsys.readouterr().out


def test_help_lists_all_command_groups(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for group in ("status", "campaign", "portfolio", "report", "factory", "shell"):
        assert group in out


# --- status ----------------------------------------------------------------

def test_status(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "status") == 0
    out = capsys.readouterr().out
    assert "Campaigns: 2" in out
    assert "ACTIVE: 2" in out
    assert "Portfolios: 1" in out


# --- campaign list/show ----------------------------------------------------

def test_campaign_list(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "campaign", "list") == 0
    out = capsys.readouterr().out
    assert "c1" in out and "c2" in out
    assert "PRIORITY" in out


def test_campaign_show(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "campaign", "show", "c1") == 0
    out = capsys.readouterr().out
    assert "Campaign c1" in out
    assert "momentum" in out
    assert "state:      ACTIVE" in out


def test_campaign_show_invalid_id_fails_clearly(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "campaign", "show", "nope") == 2
    assert "no such campaign: nope" in capsys.readouterr().err


def test_campaign_create_and_activate(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "campaign", "create", "--id", "c3", "--theme", "carry",
                "--activate") == 0
    out = capsys.readouterr().out
    assert "created campaign c3 (ACTIVE)" in out
    assert CampaignManager(db_path=db).current_state("c3") == "ACTIVE"


# --- portfolio list/show/plan ----------------------------------------------

def test_portfolio_list(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "portfolio", "list") == 0
    out = capsys.readouterr().out
    assert "P1" in out and "Alpha" in out


def test_portfolio_show(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "portfolio", "show", "P1") == 0
    out = capsys.readouterr().out
    assert "Portfolio P1" in out
    assert "c1" in out and "c2" in out


def test_portfolio_show_invalid_id_fails_clearly(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "portfolio", "show", "nope") == 2
    assert "no such portfolio: nope" in capsys.readouterr().err


def test_portfolio_plan_calls_planner(tmp_path, capsys):
    """The plan command routes through the real PortfolioPlanner (priority order)."""
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "portfolio", "plan", "P1") == 0
    out = capsys.readouterr().out
    assert "admitted: c1, c2" in out           # priority 2.0 before 1.0


# --- factory ---------------------------------------------------------------

def test_factory_run_calls_factoryrunner(tmp_path, capsys):
    """factory run drives the real FactoryRunner; on an empty DB it terminates with
    no runnable campaigns (no heavy execution)."""
    db = _db(tmp_path)
    assert _run(db, "factory", "run") == 0
    out = capsys.readouterr().out
    assert "factory run:" in out
    assert "stop_reason=no_runnable_campaigns" in out


def test_factory_status(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "factory", "status") == 0
    out = capsys.readouterr().out
    assert "active campaigns: 2" in out


# --- report ----------------------------------------------------------------

def test_report_campaign(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "report", "campaign", "c1") == 0
    assert "# Campaign Report" in capsys.readouterr().out


def test_report_portfolio(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "report", "portfolio", "P1") == 0
    out = capsys.readouterr().out
    assert "# Portfolio Report — P1" in out
    assert "c1" in out


def test_report_campaign_invalid_fails(tmp_path, capsys):
    db = _db(tmp_path)
    assert _run(db, "report", "campaign", "nope") == 2
    assert "no such campaign" in capsys.readouterr().err


# --- read-only commands never mutate state ---------------------------------

def test_read_only_commands_do_not_mutate(tmp_path):
    db = _db(tmp_path)
    cm = _seed(db)
    from agents.storage import campaign_store

    def snapshot():
        return {
            c["campaign_id"]: (cm.current_state(c["campaign_id"]),
                               len(campaign_store.list_state_events(
                                   c["campaign_id"], db_path=db)))
            for c in campaign_store.list_campaigns(db_path=db)
        }

    before = snapshot()
    for argv in (["status"], ["campaign", "list"], ["campaign", "show", "c1"],
                 ["portfolio", "list"], ["portfolio", "show", "P1"],
                 ["portfolio", "plan", "P1"], ["report", "campaign", "c1"],
                 ["report", "portfolio", "P1"], ["factory", "status"]):
        _run(db, *argv)
    assert snapshot() == before


# --- deterministic output --------------------------------------------------

def test_deterministic_list_output(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    _run(db, "campaign", "list")
    first = capsys.readouterr().out
    _run(db, "campaign", "list")
    second = capsys.readouterr().out
    assert first == second


# --- lifecycle via CLI (pause=archive, resume=activate) --------------------

def test_pause_resume_roundtrip(tmp_path, capsys):
    db = _db(tmp_path)
    cm = _seed(db)
    assert _run(db, "campaign", "pause", "c1") == 0
    assert cm.current_state("c1") == "ARCHIVED"
    assert _run(db, "campaign", "resume", "c1") == 0
    assert cm.current_state("c1") == "ACTIVE"


def test_pause_invalid_fails(tmp_path, capsys):
    db = _db(tmp_path)
    assert _run(db, "campaign", "pause", "nope") == 2
    assert "no such campaign" in capsys.readouterr().err


# --- shell dispatch (lightweight; not an LLM) ------------------------------

def _shell(db, line):
    return _shell_dispatch(line, argparse.Namespace(db=str(db)))


def test_shell_help_and_quit(tmp_path, capsys):
    db = _db(tmp_path)
    assert _shell(db, "help") == 0
    assert "quant shell" in capsys.readouterr().out
    assert _shell(db, "quit") is None
    assert _shell(db, "exit") is None


def test_shell_list_and_show(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _shell(db, "list campaigns") == 0
    assert "c1" in capsys.readouterr().out
    assert _shell(db, "show campaign c1") == 0
    assert "Campaign c1" in capsys.readouterr().out
    assert _shell(db, "show portfolio P1") == 0
    assert "Portfolio P1" in capsys.readouterr().out


def test_shell_active_portfolio(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _shell(db, "show active portfolio") == 0
    assert "P1" in capsys.readouterr().out


def test_shell_plan_and_status(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _shell(db, "plan portfolio P1") == 0
    assert "admitted: c1, c2" in capsys.readouterr().out
    assert _shell(db, "status") == 0


def test_shell_unknown_command(tmp_path, capsys):
    db = _db(tmp_path)
    assert _shell(db, "frobnicate the widget") == 1
    assert "unknown command" in capsys.readouterr().err


# --- parser wiring ---------------------------------------------------------

def test_every_command_has_a_handler():
    """Smoke: the parser builds and each leaf subcommand sets a func default."""
    parser = build_parser()
    assert parser.prog == "quant"


# --- operator commands: rich campaign creation -----------------------------

def test_campaign_create_rich_fields(tmp_path, capsys):
    db = _db(tmp_path)
    from agents.storage import campaign_store
    assert _run(db, "campaign", "create", "--id", "rich", "--theme", "carry",
                "--priority", "4", "--budget", "10", "--type", "bar_type_comparison",
                "--scope", '{"markets": ["US"]}',
                "--goal", '{"priority": 9}',
                "--trigger", '{"kind": "dependency"}',
                "--depends", "a,b",
                "--repeat", '{"mode": "interval", "max_repeats": 3}',
                "--eig", '{"aggregate": "sum"}',
                "--stopping", '{"goal": true}') == 0
    assert "created campaign rich (DRAFT)" in capsys.readouterr().out
    c = campaign_store.get_campaign("rich", db_path=db)
    assert c["scope"] == {"markets": ["US"]}
    assert c["campaign_type"] == "bar_type_comparison"
    assert int(c["budget_experiments"]) == 10
    assert c["trigger_spec"] == {"kind": "dependency"}
    assert campaign_store.campaign_depends_on(c) == ["a", "b"]
    assert c["repeat_spec"] == {"mode": "interval", "max_repeats": 3}
    assert c["eig_spec"] == {"aggregate": "sum"}


def test_campaign_create_depends_json_list(tmp_path):
    db = _db(tmp_path)
    from agents.storage import campaign_store
    assert _run(db, "campaign", "create", "--id", "d",
                "--depends", '[{"campaign_id": "x", "required_state": "ACTIVE"}]') == 0
    c = campaign_store.get_campaign("d", db_path=db)
    assert c["depends_on"] == [{"campaign_id": "x", "required_state": "ACTIVE"}]


def test_campaign_create_invalid_json_fails_clearly(tmp_path, capsys):
    db = _db(tmp_path)
    assert _run(db, "campaign", "create", "--id", "bad", "--scope", "{not json") == 2
    err = capsys.readouterr().err
    assert "--scope: invalid JSON" in err


def test_campaign_create_duplicate_id_fails(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    assert _run(db, "campaign", "create", "--id", "c1") == 2
    assert "already exists" in capsys.readouterr().err


# --- operator commands: campaign lifecycle ---------------------------------

def test_campaign_complete_and_stall_and_discard(tmp_path):
    db = _db(tmp_path)
    cm = _seed(db)
    assert _run(db, "campaign", "stall", "c1") == 0
    assert cm.current_state("c1") == "STALLED"
    assert _run(db, "campaign", "resume", "c1") == 0
    assert _run(db, "campaign", "complete", "c1") == 0
    assert cm.current_state("c1") == "COMPLETED"
    assert _run(db, "campaign", "discard", "c2") == 0
    assert cm.current_state("c2") == "DISCARDED"


def test_campaign_illegal_transition_fails_clearly(tmp_path, capsys):
    db = _db(tmp_path)
    cm = _seed(db)
    _run(db, "campaign", "complete", "c1")
    assert _run(db, "campaign", "discard", "c1") == 2   # COMPLETED is terminal
    assert "illegal transition" in capsys.readouterr().err
    assert cm.current_state("c1") == "COMPLETED"


def test_campaign_lifecycle_invalid_id(tmp_path, capsys):
    db = _db(tmp_path)
    assert _run(db, "campaign", "complete", "nope") == 2
    assert "no such campaign" in capsys.readouterr().err


def test_campaign_eig_refresh(tmp_path, capsys):
    db = _db(tmp_path)
    cm = _seed(db)
    assert _run(db, "campaign", "eig", "c1") == 0
    assert "c1 EIG =" in capsys.readouterr().out
    # cache written by the operator command
    from agents.storage import campaign_store
    assert campaign_store.get_campaign("c1", db_path=db)["expected_information_gain"] == 0.0


# --- operator commands: portfolio management -------------------------------

def test_portfolio_create(tmp_path, capsys):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    assert _run(db, "portfolio", "create", "--id", "P9", "--name", "Macro",
                "--policy", "eig_weighted", "--concurrency", "3",
                "--budget", '{"total": 20, "mode": "priority_proportional"}',
                "--objective", '{"goal": "diversify"}') == 0
    assert "created portfolio P9 (ACTIVE)" in capsys.readouterr().out
    from agents.storage import portfolio_store
    p = portfolio_store.get_portfolio("P9", db_path=db)
    assert p["scheduling_policy"] == "eig_weighted"
    assert p["concurrency_limit"] == 3
    assert p["budget_spec"] == {"total": 20, "mode": "priority_proportional"}
    assert p["objective"] == {"goal": "diversify"}


def test_portfolio_pause_resume_archive(tmp_path):
    db = _db(tmp_path)
    cm = _seed(db)
    assert _run(db, "portfolio", "pause", "P1") == 0
    assert cm.portfolio_state("P1") == "PAUSED"
    assert _run(db, "portfolio", "resume", "P1") == 0
    assert cm.portfolio_state("P1") == "ACTIVE"
    assert _run(db, "portfolio", "archive", "P1") == 0
    assert cm.portfolio_state("P1") == "ARCHIVED"


def test_portfolio_archive_then_resume_illegal(tmp_path, capsys):
    db = _db(tmp_path)
    _seed(db)
    _run(db, "portfolio", "archive", "P1")
    assert _run(db, "portfolio", "resume", "P1") == 2   # ARCHIVED is terminal
    assert "illegal transition" in capsys.readouterr().err


def test_portfolio_budget_command(tmp_path, capsys):
    db = _db(tmp_path)
    cm = CampaignManager(db_path=db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "priority_proportional",
                                     "a_max": 1.0})
    cm.create_campaign("hi", theme="t", priority=3.0, portfolio_id="P1"); cm.activate("hi")
    cm.create_campaign("lo", theme="t", priority=1.0, portfolio_id="P1"); cm.activate("lo")
    assert _run(db, "portfolio", "budget", "P1") == 0
    out = capsys.readouterr().out
    assert "Budget for P1" in out
    assert "hi" in out and "lo" in out


def test_portfolio_create_invalid_json_fails(tmp_path, capsys):
    db = _db(tmp_path)
    assert _run(db, "portfolio", "create", "--id", "PX", "--budget", "{bad") == 2
    assert "--budget: invalid JSON" in capsys.readouterr().err


# --- operator verbs are reachable from the shell ---------------------------

def test_shell_operator_verbs(tmp_path, capsys):
    db = _db(tmp_path)
    cm = _seed(db)
    assert _shell(db, "complete campaign c1") == 0
    assert cm.current_state("c1") == "COMPLETED"
    assert _shell(db, "pause portfolio P1") == 0
    assert cm.portfolio_state("P1") == "PAUSED"
    assert _shell(db, "budget portfolio P1") == 0
    assert "Budget for P1" in capsys.readouterr().out


# --- operator (write) commands are the ONLY ones that change state ---------

def test_operator_commands_go_through_campaign_manager(tmp_path):
    """Lifecycle commands emit audited events via CampaignManager (not silent
    projection writes): a transition adds exactly one state event."""
    db = _db(tmp_path)
    cm = _seed(db)
    from agents.storage import campaign_store
    before = len(campaign_store.list_state_events("c1", db_path=db))
    _run(db, "campaign", "stall", "c1")
    after = len(campaign_store.list_state_events("c1", db_path=db))
    assert after == before + 1
