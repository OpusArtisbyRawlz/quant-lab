"""Milestone 10 PR-4 — ResearchStrategist.

A deterministic decision layer that decides *what hypothesis to test next and
why* by evolving a campaign's hypothesis tree and proposing ideas into the
existing human approval queue. It never executes, schedules, or approves
anything, and it never bypasses the human gate.
"""

from .strategist import (
    ResearchStrategist,
    StrategistConfig,
    Proposal,
    ApplyResult,
    StrategistError,
)

__all__ = [
    "ResearchStrategist",
    "StrategistConfig",
    "Proposal",
    "ApplyResult",
    "StrategistError",
]
