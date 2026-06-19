"""
markdown — pure rendering helpers: dataclasses in, markdown strings out.

No database access lives here. Every function takes already-computed dataclasses
(from summaries.py) and formats them as GitHub-flavoured markdown tables. This
keeps formatting trivially unit-testable without a DB.
"""

from __future__ import annotations

from .report_store import (
    SourceModelStat,
    GroupStat,
    ComboStat,
    FunnelStat,
    CountStat,
    DecisionStat,
    BucketStat,
    OverviewStat,
)


def _fmt(x: float | None, ndigits: int = 3) -> str:
    """Render a possibly-NULL number; em dash for None."""
    return "—" if x is None else f"{x:.{ndigits}f}"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(cells) + " |"
        for cells in rows
    ]
    if not body:
        body = ["| " + " | ".join("—" for _ in headers) + " |"]
    return "\n".join([head, sep, *body])


def render_overview(o: OverviewStat) -> str:
    lines = [
        f"- **Experiments:** {o.total_experiments} "
        f"({o.idea_experiments} from LLM ideas)",
        f"- **Ideas proposed:** {o.total_ideas}",
        f"- **Lessons recorded:** {o.total_lessons}",
        f"- **Avg net Sharpe:** {_fmt(o.avg_net_sharpe)} "
        f"(over {o.n_with_net} experiments with net metrics)",
    ]
    return "\n".join(lines)


def render_source_models(stats: list[SourceModelStat]) -> str:
    rows = [
        [s.source_model, str(s.n_experiments), str(s.n_with_net),
         _fmt(s.avg_net_sharpe), _fmt(s.avg_net_calmar), _pct(s.keep_rate)]
        for s in stats
    ]
    return _table(
        ["Source model", "Experiments", "With net", "Avg net Sharpe",
         "Avg net Calmar", "Keep rate"],
        rows,
    )


def render_groups(stats: list[GroupStat], key_header: str) -> str:
    rows = [
        [s.key, str(s.n_experiments), str(s.n_with_net),
         _fmt(s.avg_net_sharpe), _fmt(s.avg_net_calmar), _pct(s.keep_rate)]
        for s in stats
    ]
    return _table(
        [key_header, "Experiments", "With net", "Avg net Sharpe",
         "Avg net Calmar", "Keep rate"],
        rows,
    )


def render_combos(stats: list[ComboStat]) -> str:
    rows = [
        [s.market, s.universe, s.source_model, str(s.n_experiments),
         _fmt(s.avg_net_sharpe), _pct(s.keep_rate)]
        for s in stats
    ]
    return _table(
        ["Market", "Universe", "Source model", "Experiments",
         "Avg net Sharpe", "Keep rate"],
        rows,
    )


def render_funnel(f: FunnelStat) -> str:
    rows = [
        ["Total proposed", str(f.total)],
        ["Pending", str(f.pending)],
        ["Approved", str(f.approved)],
        ["Executing", str(f.executing)],
        ["Executed", str(f.executed)],
        ["Rejected", str(f.rejected)],
        ["Approval rate", _pct(f.approval_rate)],
        ["Rejection rate", _pct(f.rejection_rate)],
        ["Execution rate", _pct(f.execution_rate)],
    ]
    return _table(["Stage", "Value"], rows)


def render_counts(stats: list[CountStat], label_header: str) -> str:
    rows = [[s.label, str(s.count)] for s in stats]
    return _table([label_header, "Count"], rows)


def render_decisions(d: DecisionStat) -> str:
    rows = [
        ["Total critiqued", str(d.total)],
        ["Keep", str(d.keep)],
        ["Retest", str(d.retest)],
        ["Reject", str(d.reject)],
        ["Keep rate", _pct(d.keep_rate)],
        ["Survival rate (keep+retest)", _pct(d.survival_rate)],
    ]
    return _table(["Critic decision", "Value"], rows)


def render_net_sharpe(buckets: list[BucketStat]) -> str:
    def _label(b: BucketStat) -> str:
        if b.lower is None:
            return f"< {b.upper:g}"
        if b.upper is None:
            return f">= {b.lower:g}"
        return f"[{b.lower:g}, {b.upper:g})"

    rows = [[_label(b), str(b.count)] for b in buckets]
    return _table(["Net Sharpe bucket", "Count"], rows)
