"""
summaries — the public programmatic reporting API.

Thin, stable wrappers over report_store. These are the names other code and
tests should import. They add no DB access of their own; every function simply
delegates to report_store and returns its typed dataclasses. Keeping this layer
separate lets the SQL in report_store evolve without changing the public API.
"""

from __future__ import annotations

from pathlib import Path

from agents.storage.db import DB_PATH
from . import report_store as rs
from . import context_report_store as crs
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
from .context_report_store import (
    ContextCellStat,
    GeneralizationStat,
    LifecycleEventStat,
)

__all__ = [
    "source_model_summary",
    "market_summary",
    "universe_summary",
    "combo_summary",
    "idea_funnel_summary",
    "rejection_reason_summary",
    "critic_decision_summary",
    "lesson_summary",
    "robustness_summary",
    "net_sharpe_distribution",
    "research_overview",
    # Milestone 9 context-aware summaries
    "signal_context_summary",
    "context_leaderboard",
    "signal_generalization_summary",
    "lifecycle_audit_summary",
    # dataclasses re-exported for typed callers
    "ContextCellStat",
    "GeneralizationStat",
    "LifecycleEventStat",
    "SourceModelStat",
    "GroupStat",
    "ComboStat",
    "FunnelStat",
    "CountStat",
    "DecisionStat",
    "BucketStat",
    "OverviewStat",
]


def source_model_summary(db_path: Path = DB_PATH) -> list[SourceModelStat]:
    """Per-model performance, best average net Sharpe first.

    Objective: which source_model produces the best experiments?
    """
    return rs.source_model_stats(db_path)


def market_summary(db_path: Path = DB_PATH) -> list[GroupStat]:
    """Per-market performance roll-up. Objective: best markets."""
    return rs.market_stats(db_path)


def universe_summary(db_path: Path = DB_PATH) -> list[GroupStat]:
    """Per-universe performance roll-up. Objective: best universes."""
    return rs.universe_stats(db_path)


def combo_summary(db_path: Path = DB_PATH, min_n: int = 1) -> list[ComboStat]:
    """Best market+universe+source_model combinations (min_n filters thin cells)."""
    return rs.combo_stats(db_path, min_n=min_n)


def idea_funnel_summary(db_path: Path = DB_PATH) -> FunnelStat:
    """Idea lifecycle counts + acceptance/rejection/execution rates."""
    return rs.idea_funnel(db_path)


def rejection_reason_summary(db_path: Path = DB_PATH) -> list[CountStat]:
    """Most common idea-validation rejection reasons, most frequent first."""
    return rs.rejection_reasons(db_path)


def critic_decision_summary(db_path: Path = DB_PATH) -> DecisionStat:
    """Critic keep/reject/retest breakdown + how many ideas survive the Critic."""
    return rs.critic_decisions(db_path)


def lesson_summary(db_path: Path = DB_PATH) -> list[CountStat]:
    """Lesson-category frequencies, most frequent first."""
    return rs.lesson_categories(db_path)


def robustness_summary(db_path: Path = DB_PATH) -> list[CountStat]:
    """Robustness-flag frequencies across all experiments."""
    return rs.robustness_flag_counts(db_path)


def net_sharpe_distribution(
    db_path: Path = DB_PATH,
    edges: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5, 2.0),
) -> list[BucketStat]:
    """Histogram of net Sharpe over experiments that have a net Sharpe."""
    return rs.net_sharpe_buckets(db_path, edges=edges)


def research_overview(db_path: Path = DB_PATH) -> OverviewStat:
    """Top-level counts for the report header."""
    return rs.overview(db_path)


# ---------------------------------------------------------------------------
# Milestone 9 — context-aware signal intelligence
# ---------------------------------------------------------------------------

def signal_context_summary(
    *,
    feature_name: str | None = None,
    market: str | None = None,
    universe: str | None = None,
    regime: str | None = None,
    bar_type: str | None = None,
    min_n: int | None = None,
    db_path: Path = DB_PATH,
) -> list[ContextCellStat]:
    """Signal performance per context cell, filtered to any subset of context.

    Objective: distinguish signal quality from market/universe/regime dependency.
    """
    return crs.signal_context_summary(
        feature_name=feature_name, market=market, universe=universe,
        regime=regime, bar_type=bar_type, min_n=min_n, db_path=db_path)


def context_leaderboard(
    *,
    market: str | None = None,
    universe: str | None = None,
    regime: str | None = None,
    bar_type: str | None = None,
    min_n: int | None = None,
    top: int = 10,
    db_path: Path = DB_PATH,
) -> list[ContextCellStat]:
    """Best signals within a context. Objective: 'which signals work best in X'."""
    return crs.context_leaderboard(
        market=market, universe=universe, regime=regime, bar_type=bar_type,
        min_n=min_n, top=top, db_path=db_path)


def signal_generalization_summary(
    db_path: Path = DB_PATH) -> list[GeneralizationStat]:
    """Per-signal breadth + lifecycle standing. Objective: who generalises."""
    return crs.signal_generalization_report(db_path=db_path)


def lifecycle_audit_summary(
    feature_name: str | None = None,
    db_path: Path = DB_PATH) -> list[LifecycleEventStat]:
    """Lifecycle transitions over time. Objective: when/why signals moved state."""
    return crs.lifecycle_audit_report(feature_name=feature_name, db_path=db_path)
