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
    # dataclasses re-exported for typed callers
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
