"""
Milestone 6 — Gated LLM Idea Generator.

Strict pipeline: LLM Idea Generation -> Deterministic Validation -> Human
Approval Queue -> Research Backlog.

The LLM is a *proposer only*. Nothing in this package executes a backtest,
writes an experiment row, invokes the Critic/Ledger, retries, schedules, or
touches the signal library. Approved ideas remain queued for a future
milestone to consume.
"""

from .llm_client import IdeaLLM, FakeIdeaLLM
from .idea_validator import IdeaValidationResult, validate_idea
from .idea_generator import generate_ideas
from . import approval_queue

__all__ = [
    "IdeaLLM",
    "FakeIdeaLLM",
    "IdeaValidationResult",
    "validate_idea",
    "generate_ideas",
    "approval_queue",
]
