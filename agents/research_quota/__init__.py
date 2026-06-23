"""
research_quota — Milestone 10 PR-8 exploration quota + anti-mode-collapse layer.

A deterministic, storage-free planner that enforces an exploration quota and
context-diversity safeguards over a pre-ranked candidate stream. Used by the
ResearchScheduler to keep dispatch from collapsing onto a single high-value
exploit context.
"""

from .quota import (
    BUCKET_EXPLORE,
    BUCKET_EXPLOIT,
    QuotaConfig,
    Candidate,
    QuotaPlan,
    ExplorationPlanner,
)

__all__ = [
    "BUCKET_EXPLORE",
    "BUCKET_EXPLOIT",
    "QuotaConfig",
    "Candidate",
    "QuotaPlan",
    "ExplorationPlanner",
]
