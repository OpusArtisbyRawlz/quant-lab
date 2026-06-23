"""Milestone 10 PR-5 — ResearchPrioritizer.

A deterministic, explainable ranking layer over the existing human approval
queue. It scores ``pending`` ideas by *Research Value* — a transparent weighted
blend of Expected Information Gain, Novelty, Memory Score, Campaign Priority, and
Cost — and orders them while enforcing an exploration quota so high-scoring
exploit ideas can never fully crowd out exploration.

It is read-only with respect to state: it never executes, schedules, approves,
mutates ideas, or touches the M7 execution path or the M9 learning path. It only
*reads* ideas + M9/campaign/memory evidence and *returns* an ordering with a full
per-idea score breakdown. The human approval gate is untouched.
"""

from .prioritizer import (
    ResearchPrioritizer,
    PrioritizerConfig,
    ScoreBreakdown,
    RankedIdea,
    PrioritizerError,
)

__all__ = [
    "ResearchPrioritizer",
    "PrioritizerConfig",
    "ScoreBreakdown",
    "RankedIdea",
    "PrioritizerError",
]
