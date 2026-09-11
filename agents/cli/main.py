"""
quant — a thin command-line interface over the existing Quant Research Factory.

Interface layer only. Each command is a small adapter that calls an existing
service and formats the result; it introduces no research logic, no new agent, no
orchestration, no scheduling, no persistence, and no new state. Read-only commands
never mutate the database.

Services reused:
  - CampaignManager        — campaign/portfolio lifecycle + eligibility (sole writer)
  - PortfolioPlanner       — pure planning / budget policy
  - FactoryRunner          — the thin, stateless driver (factory run)
  - ResearchLoop           — one deterministic tick (campaign/portfolio run)
  - agents.reporting.*     — markdown read-models (reports)
  - campaign_store / portfolio_store — read-only projections for listings

Command surface (see docs/QUANT_CLI.md):
  quant status
  quant campaign list|create|show|run|pause|resume
  quant portfolio list|show|plan|run
  quant report campaign|portfolio
  quant factory run|status
  quant shell         (lightweight interactive command shell — not an LLM)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


class _CliError(Exception):
    """A user-facing CLI error (bad JSON arg, unknown id, illegal transition)."""

from agents.storage.db import DB_PATH
from agents.storage import campaign_store, portfolio_store


# --------------------------------------------------------------------------- #
# Small helpers (pure formatting + service construction)
# --------------------------------------------------------------------------- #

def _db_path(args: argparse.Namespace) -> Path:
    return Path(args.db) if getattr(args, "db", None) else DB_PATH


def _manager(args: argparse.Namespace):
    from agents.campaign_manager import CampaignManager
    return CampaignManager(db_path=_db_path(args))


def _planner(args: argparse.Namespace):
    from agents.portfolio_planner import PortfolioPlanner
    return PortfolioPlanner(db_path=_db_path(args))


def _json_arg(value: str | None, name: str) -> Any:
    """Parse a JSON-valued CLI flag, or None. Raises _CliError with a clear message
    on malformed JSON so structured campaign/portfolio config can be passed inline."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise _CliError(f"--{name}: invalid JSON ({exc})")


def _depends_arg(value: str | None) -> Any:
    """Parse --depends as either a JSON list (bare ids or {campaign_id,required_state}
    dicts) or a convenience comma-separated list of bare campaign ids."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.startswith("["):
        return _json_arg(value, "depends")
    return [tok.strip() for tok in value.split(",") if tok.strip()]


def _fmt_table(rows: list[list[str]], headers: list[str]) -> str:
    """Render a simple fixed-width text table (deterministic; no external deps)."""
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    sep = "  ".join("-" * w for w in widths)
    body = [
        "  ".join(str(c).ljust(w) for c, w in zip(r, widths)) for r in rows
    ]
    return "\n".join([line, sep, *body]) if rows else line + "\n(none)"


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #

def cmd_status(args: argparse.Namespace) -> int:
    db = _db_path(args)
    campaigns = campaign_store.list_campaigns(db_path=db)
    portfolios = portfolio_store.list_portfolios(db_path=db)
    by_state: dict[str, int] = {}
    for c in campaigns:
        by_state[c["state"]] = by_state.get(c["state"], 0) + 1
    print(f"Quant Research Factory — {db}")
    print(f"Campaigns: {len(campaigns)}")
    for st in sorted(by_state):
        print(f"  {st}: {by_state[st]}")
    print(f"Portfolios: {len(portfolios)}")
    pf_state: dict[str, int] = {}
    for p in portfolios:
        pf_state[p["state"]] = pf_state.get(p["state"], 0) + 1
    for st in sorted(pf_state):
        print(f"  {st}: {pf_state[st]}")
    return 0


# --------------------------------------------------------------------------- #
# campaign
# --------------------------------------------------------------------------- #

def _campaign_progress(db: Path, campaign_id: str) -> str:
    done = campaign_store.count_campaign_experiments(campaign_id, db_path=db)
    row = campaign_store.get_campaign(campaign_id, db_path=db) or {}
    budget = int(row.get("budget_experiments", 0) or 0)
    return f"{done}/{budget}" if budget else f"{done}/∞"


def cmd_campaign_list(args: argparse.Namespace) -> int:
    db = _db_path(args)
    rows = []
    for c in campaign_store.list_campaigns(db_path=db):
        cid = c["campaign_id"]
        rows.append([
            cid, c["state"], c.get("campaign_type", ""),
            str(campaign_store.campaign_priority(c)),
            c.get("portfolio_id") or "-",
            _campaign_progress(db, cid),
        ])
    print(_fmt_table(rows, ["ID", "STATE", "TYPE", "PRIORITY", "PORTFOLIO", "PROGRESS"]))
    return 0


def cmd_campaign_create(args: argparse.Namespace) -> int:
    cm = _manager(args)
    db = _db_path(args)
    campaign_id = args.id or f"campaign-{len(campaign_store.list_campaigns(db_path=db)) + 1}"
    try:
        cm.create_campaign(
            campaign_id, theme=args.theme,
            goal_spec=_json_arg(args.goal, "goal"),
            scope=_json_arg(args.scope, "scope"),
            budget_experiments=args.budget,
            exploration_fraction=args.exploration,
            stall_patience=args.stall_patience,
            stopping_spec=_json_arg(args.stopping, "stopping"),
            campaign_type=args.type,
            priority=args.priority,
            trigger_spec=_json_arg(args.trigger, "trigger"),
            depends_on=_depends_arg(args.depends),
            eig_spec=_json_arg(args.eig, "eig"),
            repeat_spec=_json_arg(args.repeat, "repeat"),
            portfolio_id=args.portfolio,
        )
    except _CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # CampaignError etc.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.activate:
        cm.activate(campaign_id)
    print(f"created campaign {campaign_id} ({cm.current_state(campaign_id)})")
    return 0


def _campaign_transition(args: argparse.Namespace, verb: str) -> int:
    """Drive a named campaign lifecycle transition through the existing
    CampaignManager (audited, validated). verb ∈ complete/discard/stall."""
    cm = _manager(args)
    cid = args.campaign_id
    if campaign_store.get_campaign(cid, db_path=_db_path(args)) is None:
        print(f"error: no such campaign: {cid}", file=sys.stderr)
        return 2
    try:
        {"complete": cm.complete, "discard": cm.discard,
         "stall": cm.mark_stalled}[verb](cid)
    except Exception as exc:  # CampaignError on an illegal transition
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{cid} → {cm.current_state(cid)}")
    return 0


def cmd_campaign_complete(args: argparse.Namespace) -> int:
    return _campaign_transition(args, "complete")


def cmd_campaign_discard(args: argparse.Namespace) -> int:
    return _campaign_transition(args, "discard")


def cmd_campaign_stall(args: argparse.Namespace) -> int:
    return _campaign_transition(args, "stall")


def cmd_campaign_eig(args: argparse.Namespace) -> int:
    """Operator refresh of a campaign's cached EIG (P6-14). Recomputes from
    budget_allocation.evoi via CampaignManager and caches it on the campaign row."""
    cm = _manager(args)
    cid = args.campaign_id
    if campaign_store.get_campaign(cid, db_path=_db_path(args)) is None:
        print(f"error: no such campaign: {cid}", file=sys.stderr)
        return 2
    value = cm.refresh_eig(cid)
    print(f"{cid} EIG = {value}")
    return 0


def cmd_campaign_show(args: argparse.Namespace) -> int:
    db = _db_path(args)
    c = campaign_store.get_campaign(args.campaign_id, db_path=db)
    if c is None:
        print(f"error: no such campaign: {args.campaign_id}", file=sys.stderr)
        return 2
    cm = _manager(args)
    print(f"Campaign {c['campaign_id']}")
    print(f"  theme:      {c.get('theme', '')}")
    print(f"  state:      {cm.current_state(c['campaign_id'])}")
    print(f"  type:       {c.get('campaign_type', '')}")
    print(f"  priority:   {campaign_store.campaign_priority(c)}")
    print(f"  portfolio:  {c.get('portfolio_id') or '-'}")
    print(f"  progress:   {_campaign_progress(db, c['campaign_id'])}")
    print(f"  depends_on: {campaign_store.campaign_depends_on(c) or '-'}")
    print(f"  eligible:   {cm.is_eligible(c['campaign_id'])}")
    return 0


def _lifecycle(args: argparse.Namespace, verb: str) -> int:
    """pause → archive (shelve); resume → activate. Both go through the existing
    CampaignManager transitions (audited, event-sourced)."""
    cm = _manager(args)
    cid = args.campaign_id
    if campaign_store.get_campaign(cid, db_path=_db_path(args)) is None:
        print(f"error: no such campaign: {cid}", file=sys.stderr)
        return 2
    try:
        if verb == "pause":
            cm.archive(cid, reason_code="cli_pause")
        else:
            cm.activate(cid, reason_code="cli_resume")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{cid} → {cm.current_state(cid)}")
    return 0


def cmd_campaign_pause(args: argparse.Namespace) -> int:
    return _lifecycle(args, "pause")


def cmd_campaign_resume(args: argparse.Namespace) -> int:
    return _lifecycle(args, "resume")


def cmd_campaign_run(args: argparse.Namespace) -> int:
    db = _db_path(args)
    cid = args.campaign_id
    if campaign_store.get_campaign(cid, db_path=db) is None:
        print(f"error: no such campaign: {cid}", file=sys.stderr)
        return 2
    from agents.research_loop.loop import ResearchLoop
    cm = _manager(args)
    loop = ResearchLoop(db_path=db, campaign_manager=cm)
    ran = 0
    for _ in range(max(1, args.ticks)):
        loop.run_tick(cid)
        cm.advance(cid)
        ran += 1
    print(f"ran {ran} tick(s) on {cid}; state {cm.current_state(cid)}")
    return 0


# --------------------------------------------------------------------------- #
# portfolio
# --------------------------------------------------------------------------- #

def cmd_portfolio_list(args: argparse.Namespace) -> int:
    db = _db_path(args)
    rows = []
    for p in portfolio_store.list_portfolios(db_path=db):
        pid = p["portfolio_id"]
        members = portfolio_store.campaigns_in_portfolio(pid, db_path=db)
        rows.append([pid, p.get("name", ""), p["state"],
                     p.get("scheduling_policy", ""), str(len(members))])
    print(_fmt_table(rows, ["ID", "NAME", "STATE", "POLICY", "CAMPAIGNS"]))
    return 0


def cmd_portfolio_create(args: argparse.Namespace) -> int:
    cm = _manager(args)
    db = _db_path(args)
    portfolio_id = args.id or f"portfolio-{len(portfolio_store.list_portfolios(db_path=db)) + 1}"
    try:
        cm.create_portfolio(
            portfolio_id, name=args.name,
            objective=_json_arg(args.objective, "objective"),
            scheduling_policy=args.policy,
            concurrency_limit=args.concurrency,
            budget_spec=_json_arg(args.budget, "budget"),
            stopping_spec=_json_arg(args.stopping, "stopping"),
        )
    except _CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # PortfolioError etc.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"created portfolio {portfolio_id} ({cm.portfolio_state(portfolio_id)})")
    return 0


def _portfolio_transition(args: argparse.Namespace, verb: str) -> int:
    """pause/resume/archive a portfolio via the existing CampaignManager portfolio
    state machine (audited, event-sourced)."""
    cm = _manager(args)
    pid = args.portfolio_id
    if portfolio_store.get_portfolio(pid, db_path=_db_path(args)) is None:
        print(f"error: no such portfolio: {pid}", file=sys.stderr)
        return 2
    try:
        {"pause": cm.pause_portfolio, "resume": cm.resume_portfolio,
         "archive": cm.archive_portfolio}[verb](pid)
    except Exception as exc:  # PortfolioError on an illegal transition
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{pid} → {cm.portfolio_state(pid)}")
    return 0


def cmd_portfolio_pause(args: argparse.Namespace) -> int:
    return _portfolio_transition(args, "pause")


def cmd_portfolio_resume(args: argparse.Namespace) -> int:
    return _portfolio_transition(args, "resume")


def cmd_portfolio_archive(args: argparse.Namespace) -> int:
    return _portfolio_transition(args, "archive")


def cmd_portfolio_budget(args: argparse.Namespace) -> int:
    db = _db_path(args)
    if portfolio_store.get_portfolio(args.portfolio_id, db_path=db) is None:
        print(f"error: no such portfolio: {args.portfolio_id}", file=sys.stderr)
        return 2
    alloc = _planner(args).allocate_budget(args.portfolio_id)
    print(f"Budget for {alloc.portfolio_id} (mode={alloc.mode}, total={alloc.total}, "
          f"headroom={alloc.headroom})")
    rows = [[cid, str(slots)] for cid, slots in sorted(alloc.allocations.items())]
    print(_fmt_table(rows, ["CAMPAIGN", "SLOTS"]))
    return 0


def cmd_portfolio_show(args: argparse.Namespace) -> int:
    db = _db_path(args)
    p = portfolio_store.get_portfolio(args.portfolio_id, db_path=db)
    if p is None:
        print(f"error: no such portfolio: {args.portfolio_id}", file=sys.stderr)
        return 2
    members = portfolio_store.campaigns_in_portfolio(args.portfolio_id, db_path=db)
    print(f"Portfolio {p['portfolio_id']}")
    print(f"  name:        {p.get('name', '')}")
    print(f"  state:       {p['state']}")
    print(f"  policy:      {p.get('scheduling_policy', '')}")
    print(f"  concurrency: {p.get('concurrency_limit', 0)}")
    print(f"  campaigns:   {', '.join(members) if members else '-'}")
    return 0


def cmd_portfolio_plan(args: argparse.Namespace) -> int:
    db = _db_path(args)
    if portfolio_store.get_portfolio(args.portfolio_id, db_path=db) is None:
        print(f"error: no such portfolio: {args.portfolio_id}", file=sys.stderr)
        return 2
    plan = _planner(args).plan(args.portfolio_id)
    print(f"Plan for {plan.portfolio_id} (policy={plan.policy}, "
          f"concurrency_limit={plan.concurrency_limit})")
    print(f"  admitted: {', '.join(plan.admitted) if plan.admitted else '-'}")
    if plan.excluded_cycles:
        print(f"  excluded (cycle): {', '.join(plan.excluded_cycles)}")
    return 0


def cmd_portfolio_run(args: argparse.Namespace) -> int:
    db = _db_path(args)
    if portfolio_store.get_portfolio(args.portfolio_id, db_path=db) is None:
        print(f"error: no such portfolio: {args.portfolio_id}", file=sys.stderr)
        return 2
    cm = _manager(args)
    admitted = _planner(args).plan(args.portfolio_id).admitted
    if not admitted:
        print(f"no runnable campaigns in {args.portfolio_id}")
        return 0
    from agents.research_loop.loop import ResearchLoop
    loop = ResearchLoop(db_path=db, campaign_manager=cm)
    for cid in admitted:
        loop.run_tick(cid)
        cm.advance(cid)
    print(f"ran 1 tick on {len(admitted)} campaign(s): {', '.join(admitted)}")
    return 0


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def cmd_report_campaign(args: argparse.Namespace) -> int:
    db = _db_path(args)
    if campaign_store.get_campaign(args.campaign_id, db_path=db) is None:
        print(f"error: no such campaign: {args.campaign_id}", file=sys.stderr)
        return 2
    from agents.reporting.campaign_report import generate_campaign_report
    print(generate_campaign_report(args.campaign_id, db_path=db))
    return 0


def cmd_report_portfolio(args: argparse.Namespace) -> int:
    db = _db_path(args)
    p = portfolio_store.get_portfolio(args.portfolio_id, db_path=db)
    if p is None:
        print(f"error: no such portfolio: {args.portfolio_id}", file=sys.stderr)
        return 2
    # Compose a concise portfolio report from existing reads (no new read-model).
    members = portfolio_store.campaigns_in_portfolio(args.portfolio_id, db_path=db)
    plan = _planner(args).plan(args.portfolio_id)
    print(f"# Portfolio Report — {p['portfolio_id']}")
    print(f"_state={p['state']} policy={p.get('scheduling_policy', '')} "
          f"concurrency_limit={p.get('concurrency_limit', 0)}_\n")
    rows = []
    for cid in members:
        c = campaign_store.get_campaign(cid, db_path=db) or {}
        rows.append([cid, c.get("state", ""),
                     str(campaign_store.campaign_priority(c)),
                     _campaign_progress(db, cid)])
    print(_fmt_table(rows, ["CAMPAIGN", "STATE", "PRIORITY", "PROGRESS"]))
    print(f"\nCurrent plan (admitted): "
          f"{', '.join(plan.admitted) if plan.admitted else '-'}")
    return 0


# --------------------------------------------------------------------------- #
# factory
# --------------------------------------------------------------------------- #

def cmd_factory_run(args: argparse.Namespace) -> int:
    from agents.research_loop.factory_runner import FactoryRunner
    report = FactoryRunner(db_path=_db_path(args)).run(
        max_ticks=args.ticks, max_rounds=args.rounds)
    print(f"factory run: ticks={report.ticks} rounds={report.rounds} "
          f"stop_reason={report.stop_reason}")
    if report.ticked:
        print(f"  ticked: {', '.join(report.ticked)}")
    return 0


def cmd_factory_status(args: argparse.Namespace) -> int:
    db = _db_path(args)
    from agents.storage import loop_store
    campaigns = campaign_store.list_campaigns(db_path=db)
    active = [c["campaign_id"] for c in campaigns if c["state"] == "ACTIVE"]
    latest = loop_store.latest_tick_id(db_path=db)
    print("Factory status")
    print(f"  active campaigns: {len(active)}")
    if active:
        print(f"    {', '.join(active)}")
    print(f"  latest tick: {latest or '-'}")
    return 0


# --------------------------------------------------------------------------- #
# interactive shell (lightweight; NOT an LLM)
# --------------------------------------------------------------------------- #

_SHELL_HELP = """\
quant shell — operational commands over the existing factory (type 'help' or 'quit')
  status
  list campaigns | list portfolios
  show campaign <id> | show portfolio <id> | show active portfolio(s)
  plan portfolio <id> | budget portfolio <id>
  run campaign <id> | run portfolio <id> | run factory
  pause|resume|complete|discard|stall campaign <id>
  pause|resume|archive portfolio <id>
  report campaign <id> | show latest report
"""


def _shell_dispatch(line: str, args: argparse.Namespace) -> int | None:
    """Map a lightweight command line to the existing handlers. Returns an exit
    code, or None to signal 'quit'. Pure keyword parsing — no NLP."""
    toks = line.split()
    if not toks:
        return 0
    verb, rest = toks[0].lower(), toks[1:]
    ns = argparse.Namespace(db=getattr(args, "db", None))

    if verb in ("quit", "exit"):
        return None
    if verb == "help":
        print(_SHELL_HELP)
        return 0
    if verb == "status":
        return cmd_status(ns)
    if verb == "list" and rest:
        if rest[0].startswith("campaign"):
            return cmd_campaign_list(ns)
        if rest[0].startswith("portfolio"):
            return cmd_portfolio_list(ns)
    if verb == "show" and rest:
        if rest[0].startswith("active") and len(rest) >= 2 and rest[1].startswith("portfolio"):
            for p in portfolio_store.list_portfolios(state="ACTIVE", db_path=_db_path(ns)):
                print(f"{p['portfolio_id']}  {p.get('name', '')}")
            return 0
        if rest[0] == "latest" and len(rest) >= 2 and rest[1].startswith("report"):
            from agents.reporting.report import generate_research_report
            print(generate_research_report(db_path=_db_path(ns)))
            return 0
        if rest[0].startswith("campaign") and len(rest) >= 2:
            ns.campaign_id = rest[1]
            return cmd_campaign_show(ns)
        if rest[0].startswith("portfolio") and len(rest) >= 2:
            ns.portfolio_id = rest[1]
            return cmd_portfolio_show(ns)
    if verb == "plan" and len(rest) >= 2 and rest[0].startswith("portfolio"):
        ns.portfolio_id = rest[1]
        return cmd_portfolio_plan(ns)
    if verb == "run" and rest:
        if rest[0] == "factory":
            ns.ticks, ns.rounds = 1, 1
            return cmd_factory_run(ns)
        if rest[0].startswith("campaign") and len(rest) >= 2:
            ns.campaign_id, ns.ticks = rest[1], 1
            return cmd_campaign_run(ns)
        if rest[0].startswith("portfolio") and len(rest) >= 2:
            ns.portfolio_id = rest[1]
            return cmd_portfolio_run(ns)
    if verb == "report" and len(rest) >= 2 and rest[0].startswith("campaign"):
        ns.campaign_id = rest[1]
        return cmd_report_campaign(ns)
    if verb == "budget" and len(rest) >= 2 and rest[0].startswith("portfolio"):
        ns.portfolio_id = rest[1]
        return cmd_portfolio_budget(ns)
    # Campaign lifecycle operator verbs: "<verb> campaign <id>".
    _CAMP_VERBS = {"pause": cmd_campaign_pause, "resume": cmd_campaign_resume,
                   "complete": cmd_campaign_complete, "discard": cmd_campaign_discard,
                   "stall": cmd_campaign_stall}
    if verb in _CAMP_VERBS and len(rest) >= 2 and rest[0].startswith("campaign"):
        ns.campaign_id = rest[1]
        return _CAMP_VERBS[verb](ns)
    # Portfolio lifecycle operator verbs: "<verb> portfolio <id>".
    _PF_VERBS = {"pause": cmd_portfolio_pause, "resume": cmd_portfolio_resume,
                 "archive": cmd_portfolio_archive}
    if verb in _PF_VERBS and len(rest) >= 2 and rest[0].startswith("portfolio"):
        ns.portfolio_id = rest[1]
        return _PF_VERBS[verb](ns)

    print(f"unknown command: {line!r} (type 'help')", file=sys.stderr)
    return 1


def cmd_shell(args: argparse.Namespace) -> int:
    """A lightweight interactive command shell over the existing factory APIs. Not
    an LLM chatbot — it maps fixed keyword commands to the same handlers used by the
    non-interactive CLI. Reads lines until EOF or 'quit'."""
    print(_SHELL_HELP)
    while True:
        try:
            line = input("quant> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        result = _shell_dispatch(line, args)
        if result is None:
            return 0


# --------------------------------------------------------------------------- #
# argument parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quant",
        description="Thin terminal interface to the Quant Research Factory.")
    p.add_argument("--db", help="path to the factory SQLite DB (default: the "
                                "repository's agents/quant_agents.db)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="factory overview (campaign/portfolio counts)"
                   ).set_defaults(func=cmd_status)

    # campaign
    camp = sub.add_parser("campaign", help="campaign operations")
    csub = camp.add_subparsers(dest="sub", required=True)
    csub.add_parser("list", help="list campaigns").set_defaults(func=cmd_campaign_list)
    cc = csub.add_parser("create", help="create a campaign (DRAFT)")
    cc.add_argument("--id", help="campaign id (auto-generated if omitted)")
    cc.add_argument("--theme", default="untitled research")
    cc.add_argument("--priority", type=float, default=None)
    cc.add_argument("--budget", type=int, default=0, help="budget_experiments (0=unbounded)")
    cc.add_argument("--type", default="strategy_evolution", help="campaign_type")
    cc.add_argument("--portfolio", default=None, help="portfolio_id")
    cc.add_argument("--goal", default=None, help="goal_spec as JSON")
    cc.add_argument("--scope", default=None, help="scope as JSON")
    cc.add_argument("--stopping", default=None, help="stopping_spec as JSON")
    cc.add_argument("--trigger", default=None, help="trigger_spec as JSON")
    cc.add_argument("--depends", default=None,
                    help="depends_on: JSON list, or comma-separated campaign ids")
    cc.add_argument("--repeat", default=None, help="repeat_spec as JSON")
    cc.add_argument("--eig", default=None, help="eig_spec as JSON")
    cc.add_argument("--exploration", type=float, default=0.34,
                    help="exploration_fraction")
    cc.add_argument("--stall-patience", dest="stall_patience", type=int, default=3)
    cc.add_argument("--activate", action="store_true", help="activate after creating")
    cc.set_defaults(func=cmd_campaign_create)
    cs = csub.add_parser("show", help="show one campaign")
    cs.add_argument("campaign_id")
    cs.set_defaults(func=cmd_campaign_show)
    cr = csub.add_parser("run", help="run tick(s) on a campaign via ResearchLoop")
    cr.add_argument("campaign_id")
    cr.add_argument("--ticks", type=int, default=1)
    cr.set_defaults(func=cmd_campaign_run)
    cp = csub.add_parser("pause", help="pause (archive/shelve) a campaign")
    cp.add_argument("campaign_id")
    cp.set_defaults(func=cmd_campaign_pause)
    cre = csub.add_parser("resume", help="resume (activate) a campaign")
    cre.add_argument("campaign_id")
    cre.set_defaults(func=cmd_campaign_resume)
    cco = csub.add_parser("complete", help="mark a campaign COMPLETED")
    cco.add_argument("campaign_id")
    cco.set_defaults(func=cmd_campaign_complete)
    cd = csub.add_parser("discard", help="discard (abandon) a campaign")
    cd.add_argument("campaign_id")
    cd.set_defaults(func=cmd_campaign_discard)
    cst = csub.add_parser("stall", help="mark a campaign STALLED")
    cst.add_argument("campaign_id")
    cst.set_defaults(func=cmd_campaign_stall)
    ce = csub.add_parser("eig", help="refresh + show a campaign's cached EIG")
    ce.add_argument("campaign_id")
    ce.set_defaults(func=cmd_campaign_eig)

    # portfolio
    pf = sub.add_parser("portfolio", help="portfolio operations")
    psub = pf.add_subparsers(dest="sub", required=True)
    psub.add_parser("list", help="list portfolios").set_defaults(func=cmd_portfolio_list)
    pcr = psub.add_parser("create", help="create a portfolio (ACTIVE)")
    pcr.add_argument("--id", help="portfolio id (auto-generated if omitted)")
    pcr.add_argument("--name", default="untitled portfolio")
    pcr.add_argument("--objective", default=None, help="objective as JSON")
    pcr.add_argument("--policy", default="priority",
                     help="scheduling_policy (priority|round_robin|eig_weighted)")
    pcr.add_argument("--concurrency", type=int, default=0,
                     help="concurrency_limit (0=unbounded)")
    pcr.add_argument("--budget", default=None, help="budget_spec as JSON")
    pcr.add_argument("--stopping", default=None, help="stopping_spec as JSON")
    pcr.set_defaults(func=cmd_portfolio_create)
    ps = psub.add_parser("show", help="show one portfolio")
    ps.add_argument("portfolio_id")
    ps.set_defaults(func=cmd_portfolio_show)
    pp = psub.add_parser("plan", help="deterministic plan via PortfolioPlanner")
    pp.add_argument("portfolio_id")
    pp.set_defaults(func=cmd_portfolio_plan)
    pb = psub.add_parser("budget", help="deterministic budget allocation (PortfolioPlanner)")
    pb.add_argument("portfolio_id")
    pb.set_defaults(func=cmd_portfolio_budget)
    pr = psub.add_parser("run", help="run one tick per admitted campaign")
    pr.add_argument("portfolio_id")
    pr.set_defaults(func=cmd_portfolio_run)
    ppa = psub.add_parser("pause", help="pause a portfolio")
    ppa.add_argument("portfolio_id")
    ppa.set_defaults(func=cmd_portfolio_pause)
    pre = psub.add_parser("resume", help="resume a portfolio")
    pre.add_argument("portfolio_id")
    pre.set_defaults(func=cmd_portfolio_resume)
    par = psub.add_parser("archive", help="archive a portfolio")
    par.add_argument("portfolio_id")
    par.set_defaults(func=cmd_portfolio_archive)

    # report
    rep = sub.add_parser("report", help="markdown read-model reports")
    rsub = rep.add_subparsers(dest="sub", required=True)
    rc = rsub.add_parser("campaign", help="campaign report")
    rc.add_argument("campaign_id")
    rc.set_defaults(func=cmd_report_campaign)
    rp = rsub.add_parser("portfolio", help="portfolio report")
    rp.add_argument("portfolio_id")
    rp.set_defaults(func=cmd_report_portfolio)

    # factory
    fac = sub.add_parser("factory", help="the continuous factory driver")
    fsub = fac.add_subparsers(dest="sub", required=True)
    fr = fsub.add_parser("run", help="drive runnable campaigns via FactoryRunner")
    fr.add_argument("--ticks", type=int, default=1, help="max ticks")
    fr.add_argument("--rounds", type=int, default=None, help="max rounds")
    fr.set_defaults(func=cmd_factory_run)
    fsub.add_parser("status", help="factory status").set_defaults(func=cmd_factory_status)

    # shell
    sub.add_parser("shell", help="interactive command shell (not an LLM)"
                   ).set_defaults(func=cmd_shell)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except _CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:  # pragma: no cover - piping to head, etc.
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
