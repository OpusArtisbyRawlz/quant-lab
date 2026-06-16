"""
Shared dataclasses for inter-agent message passing.

Phase 1 agents use these as plain data containers.
Phase 2+ will route them through a message bus.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ExperimentSpec:
    """Fully-specified experiment ready for the backtest agent."""
    hypothesis: str
    market: str
    universe: str
    target: str
    features: list[str]
    model: str
    validation_method: str
    success_criteria: dict[str, Any]
    expected_improvement: str
    project: str = ""
    notes: str = ""
    experiment_id: str = ""   # pre-set by caller; assigned by folder_writer if blank


@dataclass
class ExperimentResult:
    """Output from a completed backtest run."""
    experiment_id: str
    spec: ExperimentSpec
    metrics: dict[str, float]   # sharpe, mdd, cagr, vol, calmar
    artifact_path: str
    status: str                  # keep / reject / retest
    ran_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CritiqueResult:
    """Critic agent's assessment of an experiment result."""
    experiment_id: str
    passed: bool
    overfitting_risk: str        # low / medium / high
    drawdown_flag: bool
    decision: str                # keep / reject / retest
    notes: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentMessage:
    """A single message logged in the agent_conversations table."""
    cycle_id: str
    sender: str
    recipient: str
    message_type: str            # hypothesis / spec / result / critique / lesson / summary
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SignalRecord:
    """A feature or signal entry in the signal library."""
    feature_name: str
    signal_type: str             # momentum / mean_reversion / volatility / macro / composite
    market: str
    universe: str
    project_source: str
    experiment_ids: list[str]
    performance_contribution: float | None
    weakness: str
    possible_combinations: list[str]
    keep_reject_retest: str      # keep / reject / retest
    notes: str


@dataclass
class Lesson:
    """A distilled insight extracted after an experiment cycle."""
    experiment_id: str
    cycle_id: str
    category: str                # signal / risk / overfitting / regime / portfolio / other
    finding: str
    implication: str             # what to try / avoid next
    confidence: str              # high / medium / low
