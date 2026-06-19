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
)
from .report import generate_research_report, write_research_report

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
    "generate_research_report",
    "write_research_report",
]
