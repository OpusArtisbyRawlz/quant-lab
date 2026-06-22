"""
campaign_report — assembles the human-readable Milestone 10 campaign board.

generate_campaign_report() pulls every campaign section from the programmatic
API (summaries.py) and renders it as markdown. write_campaign_report() writes
the string to a caller-supplied path — the only filesystem write here, never the
database. Like the rest of the reporting package this module is strictly
read-only and imports no execution agents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agents.storage.db import DB_PATH
from . import summaries as s
from .campaign_report_store import HypothesisTreeNode


def _fmt(x) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def render_overviews(rows) -> str:
    if not rows:
        return "_No campaigns._"
    head = ("| Campaign | State | Exp | Hyp | Ideas | Lessons | "
            "Avg net Sharpe | Best | Budget |")
    sep = "|" + "---|" * 9
    lines = [head, sep]
    for o in rows:
        lines.append(
            f"| {o.theme or o.campaign_id} | {_fmt(o.state)} | {o.n_experiments} | "
            f"{o.n_hypotheses} | {o.n_ideas} | {o.n_lessons} | "
            f"{_fmt(o.avg_net_sharpe)} | {_fmt(o.best_net_sharpe)} | "
            f"{o.budget_spent}/{o.budget_experiments} |"
        )
    return "\n".join(lines)


def render_ranking(rows) -> str:
    if not rows:
        return "_No campaigns to rank._"
    lines = ["| Rank | Campaign | State | Experiments | Avg net Sharpe |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r.rank} | {r.theme or r.campaign_id} | {_fmt(r.state)} | "
            f"{r.n_experiments} | {_fmt(r.avg_net_sharpe)} |"
        )
    return "\n".join(lines)


def render_stalled(rows) -> str:
    if not rows:
        return "_No stalled campaigns._"
    lines = ["| Campaign | Experiments | Budget | Stall patience |",
             "|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r.theme or r.campaign_id} | {r.n_experiments} | "
            f"{r.budget_spent}/{r.budget_experiments} | {r.stall_patience} |"
        )
    return "\n".join(lines)


def render_exploration(stat) -> str:
    return (
        f"- Explore dispatches: **{stat.explore}**\n"
        f"- Exploit dispatches: **{stat.exploit}**\n"
        f"- Unknown bucket: {stat.unknown}\n"
        f"- Total dispatches: {stat.total}\n"
        f"- Explore fraction: **{_fmt(stat.explore_fraction)}**"
    )


def render_productive_contexts(rows) -> str:
    if not rows:
        return "_No context cells yet._"
    lines = ["| Signal | Market | Universe | Regime | Bar | N | "
             "Avg net Sharpe | Contribution |",
             "|" + "---|" * 8]
    for c in rows:
        lines.append(
            f"| {c.feature_name} | {c.market} | {c.universe} | {c.regime} | "
            f"{c.bar_type} | {c.n_experiments} | {_fmt(c.avg_net_sharpe)} | "
            f"{_fmt(c.contribution_score)} |"
        )
    return "\n".join(lines)


def render_recent_knowledge(rows) -> str:
    if not rows:
        return "_No lessons recorded._"
    lines = []
    for r in rows:
        conf = f" ({r.confidence})" if r.confidence else ""
        cat = f"[{r.category}] " if r.category else ""
        lines.append(f"- {cat}{_fmt(r.finding)} → {_fmt(r.implication)}{conf}")
    return "\n".join(lines)


def render_lifecycle_board(rows) -> str:
    if not rows:
        return "_No signals._"
    lines = []
    for b in rows:
        names = ", ".join(b.feature_names)
        lines.append(f"- **{b.lifecycle_state}** ({b.n_signals}): {names}")
    return "\n".join(lines)


def render_hypothesis_tree(roots: list[HypothesisTreeNode]) -> str:
    if not roots:
        return "_No hypotheses._"
    lines: list[str] = []

    def walk(node: HypothesisTreeNode) -> None:
        indent = "  " * node.depth
        op = f" _[{node.operator_in}]_" if node.operator_in else ""
        marker = " ✓" if node.experiment_id else ""
        lines.append(f"{indent}- {node.hypothesis}{op}{marker}")
        for child in node.children:
            walk(child)

    for r in roots:
        walk(r)
    return "\n".join(lines)


def generate_campaign_report(
    campaign_id: str | None = None, db_path: Path = DB_PATH
) -> str:
    """Build the complete markdown campaign board as a string.

    When campaign_id is given, the hypothesis-tree section renders that
    campaign's forest; the other sections are always system-wide."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections: list[str] = [
        "# Campaign Report",
        f"_Generated {generated_at}_",
        "## Campaign Overview",
        render_overviews(s.campaign_overview_summary(db_path=db_path)),
        "## Campaign Ranking",
        render_ranking(s.campaign_ranking_summary(db_path=db_path)),
        "## Stalled Campaigns",
        render_stalled(s.stalled_campaign_summary(db_path=db_path)),
        "## Exploration vs Exploitation",
        render_exploration(s.exploration_summary(
            campaign_id=campaign_id, db_path=db_path)),
        "## Productive Contexts",
        render_productive_contexts(s.productive_context_summary(db_path=db_path)),
        "## Recently Learned Knowledge",
        render_recent_knowledge(s.recent_knowledge_summary(db_path=db_path)),
        "## Signal Lifecycle Board",
        render_lifecycle_board(s.signal_lifecycle_board_summary(db_path=db_path)),
    ]
    if campaign_id is not None:
        sections.append("## Hypothesis Evolution Tree")
        sections.append(render_hypothesis_tree(
            s.hypothesis_tree_summary(campaign_id, db_path=db_path)))
    return "\n\n".join(sections)


def write_campaign_report(
    path: Path, campaign_id: str | None = None, db_path: Path = DB_PATH
) -> Path:
    """Write the campaign report to a caller-supplied path. Never the database."""
    path = Path(path)
    path.write_text(generate_campaign_report(campaign_id, db_path=db_path))
    return path
