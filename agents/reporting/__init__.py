"""
Research reporting & analytics (Milestone 8).

A strictly READ-ONLY layer over the SQLite store. Nothing in this package
writes to the database, mutates rows, or imports execution agents. It answers
"what has the research system learned?" by aggregating the experiments,
pending_ideas, and lessons_learned tables.

Public surface:
- summaries.py : programmatic API returning typed dataclasses.
- report.py    : generate_research_report() -> human-readable markdown.
"""

from .summaries import (
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
    signal_context_summary,
    context_leaderboard,
    signal_generalization_summary,
    lifecycle_audit_summary,
    campaign_overview_summary,
    campaign_ranking_summary,
    stalled_campaign_summary,
    exploration_summary,
    productive_context_summary,
    recent_knowledge_summary,
    signal_lifecycle_board_summary,
    hypothesis_tree_summary,
)
from .report import generate_research_report, write_research_report
from .campaign_report import generate_campaign_report, write_campaign_report

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
    "signal_context_summary",
    "context_leaderboard",
    "signal_generalization_summary",
    "lifecycle_audit_summary",
    "campaign_overview_summary",
    "campaign_ranking_summary",
    "stalled_campaign_summary",
    "exploration_summary",
    "productive_context_summary",
    "recent_knowledge_summary",
    "signal_lifecycle_board_summary",
    "hypothesis_tree_summary",
    "generate_research_report",
    "write_research_report",
    "generate_campaign_report",
    "write_campaign_report",
]
