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
    drawdown_flag: bool
    decision: str                # keep / reject / retest
    notes: str
    # Which thresholds were active and where each came from ("spec" | "config" | "none")
    thresholds_used: dict = field(default_factory=dict)
    # M7: originating approved-idea id when execution came from the idea
    # generator ("" for experiments not sourced from an idea).
    source_idea_id: str = ""
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


# ---------------------------------------------------------------------------
# Milestone 4 — agent-loop dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ResearchAgenda:
    """
    Input to the Commander. Contains the list of hypotheses to investigate
    in one research cycle. Provided by the user or a config file.
    """
    hypotheses: list[str]
    project: str
    universe: str
    market: str


@dataclass
class HypothesisTask:
    """
    One unit of work emitted by the Commander and consumed by the
    Experiment Designer. Contains a hypothesis plus signal hints.
    """
    hypothesis: str
    suggested_signals: list[str]
    project: str
    universe: str
    market: str
    priority: int = 0


@dataclass(frozen=True)
class ProposedIdea:
    """
    A single research idea proposed by the LLM Idea Generator (M6).

    Pure data — the LLM can only *fill these fields*; it cannot express an
    action, a runnable spec, or code. This is the structural enforcement of
    "LLM output is data, not commands."

    `scores` holds advisory-only heuristics (novelty / feasibility /
    signal_diversity). They are informational and NEVER gate validation,
    approval, or execution. `source_model` records provenance so idea quality
    can be analysed per-model over time.
    """
    hypothesis: str
    suggested_signals: tuple[str, ...]
    source_model: str
    rationale: str = ""
    scores: dict[str, float] | None = None
    # M7: research context stored on the idea so an approved idea is
    # self-contained and reproducible. Supplied by the caller (batch context),
    # not chosen by the LLM — consistent with "LLM output is data".
    market: str = ""
    universe: str = ""


@dataclass
class LedgerUpdate:
    """
    Receipt from the Ledger Agent after it writes decision and lesson to
    the database.
    """
    experiment_id: str
    decision: str               # keep / reject / retest
    conclusion: str
    lesson_written: bool
    lesson_category: str = ""   # "signal_quality" | "universe" | "pipeline" | "other"
    # M7: originating approved-idea id ("" when not sourced from an idea).
    source_idea_id: str = ""
    # M7.1: persistence outcome. status_written reflects the experiments-row
    # decision update; lesson_written (above) reflects the lessons_learned row.
    # `ok` is True only when BOTH writes succeeded — execution completion is
    # gated on it so a failed ledger write never marks an idea executed.
    status_written: bool = False

    @property
    def ok(self) -> bool:
        return self.status_written and self.lesson_written
