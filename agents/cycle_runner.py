"""
cycle_runner.py — single-cycle orchestrator for the M4 agent loop.

Drives: Commander → Experiment Designer → Runner → Critic → Ledger Agent.
Logs every inter-agent handoff to agent_conversations.

This is not an agent — it owns the loop and all conversation logging.
Agents themselves never import conversation_store.

Scope (M4):
  - Deterministic, rule-based only
  - No LLM, no scheduler, no auto-retry, no signal-library promotion
  - One manual cycle; call run_cycle() once per research session
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from agents.protocol import (
    CritiqueResult,
    HypothesisTask,
    LedgerUpdate,
    ResearchAgenda,
)
from agents.storage.db import DB_PATH, get_connection
from agents.storage.conversation_store import log_message
from agents.experiment_runner.runner import RunResult, run_experiment, COMPLETED_DIR, DATA_ROOT
from agents.commander.commander import Commander
from agents.experiment_designer.designer import ExperimentDesigner, DesignError
from agents.critic.critic import Critic
from agents.ledger_agent.ledger_agent import LedgerAgent

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CycleResult
# ---------------------------------------------------------------------------

@dataclass
class TaskOutcome:
    """Outcome of one task in the cycle."""
    task: HypothesisTask
    run_result:   RunResult    | None = None
    critique:     CritiqueResult | None = None
    ledger_update: LedgerUpdate | None = None
    design_error: str | None = None   # set when Designer raises DesignError


@dataclass
class CycleResult:
    """Aggregate result of one run_cycle() call."""
    cycle_id: str
    tasks_attempted: int
    tasks_succeeded: int    # RunResult.status == "success"
    tasks_failed:    int    # RunResult.status == "failed" OR DesignError
    outcomes: list[TaskOutcome] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_cycle(
    agenda: ResearchAgenda,
    *,
    db_path:       Path = DB_PATH,
    completed_dir: Path = COMPLETED_DIR,
    data_root:     Path = DATA_ROOT,
    data_dict:     dict[str, pd.DataFrame] | None = None,
    dry_run:       bool = False,
    critic_config: Path | None = None,   # path to custom TOML; None → default
) -> CycleResult:
    """
    Execute one research cycle.

    Parameters
    ----------
    agenda : ResearchAgenda
        Hypotheses to investigate.  Provided by the caller.
    db_path : Path
        SQLite database.
    completed_dir : Path
        Root of experiments/completed/.
    data_root : Path
        Root of data/raw/.
    data_dict : dict, optional
        Pre-loaded market data (testing seam — bypasses disk load).
    dry_run : bool
        If True, passes dry_run=True to run_experiment; no files written,
        no DB rows written.  Conversation log is still written.
    critic_config : Path, optional
        Custom TOML for Critic thresholds. Defaults to critic_defaults.toml.

    Returns
    -------
    CycleResult
    """
    cycle_id = _next_cycle_id(db_path)

    commander = Commander()
    designer  = ExperimentDesigner()
    runner_fn = run_experiment          # M3 function, not a class
    critic    = Critic(critic_config)
    ledger    = LedgerAgent()

    # ── Commander: filter and prioritise hypotheses ────────────────────────
    tasks = commander.run(agenda, db_path=db_path)
    log.info("Cycle %s: %d task(s) from Commander.", cycle_id, len(tasks))

    outcomes: list[TaskOutcome] = []
    succeeded = failed = 0

    for task in tasks:

        # ── Log: Commander → Designer ──────────────────────────────────────
        _log(cycle_id, "commander", "experiment_designer", "hypothesis",
             _task_payload(task), db_path)

        outcome = TaskOutcome(task=task)

        # ── Experiment Designer ────────────────────────────────────────────
        try:
            spec = designer.run(task, db_path=db_path)
        except DesignError as exc:
            log.warning("Cycle %s: DesignError for %r — %s", cycle_id, task.hypothesis, exc)
            outcome.design_error = str(exc)
            failed += 1
            outcomes.append(outcome)
            continue

        # ── Log: Designer → Runner ─────────────────────────────────────────
        _log(cycle_id, "experiment_designer", "runner", "spec",
             _spec_payload(spec), db_path)

        # ── Runner ────────────────────────────────────────────────────────
        result: RunResult = runner_fn(
            spec,
            db_path=db_path,
            completed_dir=completed_dir,
            data_root=data_root,
            data_dict=data_dict,
            dry_run=dry_run,
        )
        outcome.run_result = result

        if result.status == "success":
            succeeded += 1
        elif result.status not in ("dry_run",):
            failed += 1

        # ── Log: Runner → Critic ───────────────────────────────────────────
        _log(cycle_id, "runner", "critic", "result",
             _result_payload(result), db_path)

        # ── Critic ────────────────────────────────────────────────────────
        critique = critic.run(result, spec)
        outcome.critique = critique

        # ── Log: Critic → Ledger ───────────────────────────────────────────
        _log(cycle_id, "critic", "ledger_agent", "critique",
             _critique_payload(critique), db_path)

        # ── Ledger Agent ───────────────────────────────────────────────────
        # Skip ledger writes during dry_run to keep DB clean
        if dry_run:
            ledger_update = LedgerUpdate(
                experiment_id=result.experiment_id,
                decision=critique.decision,
                conclusion="(dry run — not persisted)",
                lesson_written=False,
            )
        else:
            ledger_update = ledger.run(result, critique, db_path=db_path)
        outcome.ledger_update = ledger_update

        # ── Log: Ledger → archive ──────────────────────────────────────────
        _log(cycle_id, "ledger_agent", "archive", "summary",
             _summary_payload(ledger_update), db_path)

        outcomes.append(outcome)

    log.info(
        "Cycle %s complete: succeeded=%d  failed=%d  total=%d",
        cycle_id, succeeded, failed, len(outcomes),
    )

    return CycleResult(
        cycle_id=cycle_id,
        tasks_attempted=len(outcomes),
        tasks_succeeded=succeeded,
        tasks_failed=failed,
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Payload builders — keep log calls in run_cycle readable
# ---------------------------------------------------------------------------

def _task_payload(task: HypothesisTask) -> dict[str, Any]:
    return {
        "hypothesis":        task.hypothesis,
        "suggested_signals": task.suggested_signals,
        "project":           task.project,
        "universe":          task.universe,
        "market":            task.market,
        "priority":          task.priority,
    }


def _spec_payload(spec: Any) -> dict[str, Any]:
    return {
        "experiment_id":     spec.experiment_id,
        "features":          spec.features,
        "model":             spec.model,
        "target":            spec.target,
        "validation_method": spec.validation_method,
        "success_criteria":  spec.success_criteria,
        "project":           spec.project,
        "universe":          spec.universe,
    }


def _result_payload(result: RunResult) -> dict[str, Any]:
    return {
        "experiment_id": result.experiment_id,
        "status":        result.status,
        "metrics":       result.metrics,
        "artifact_path": str(result.artifact_path) if result.artifact_path else None,
        "warnings":      result.warnings,
        "error":         (result.error or "")[:300] if result.error else None,
    }


def _critique_payload(critique: CritiqueResult) -> dict[str, Any]:
    return {
        "experiment_id":   critique.experiment_id,
        "passed":          critique.passed,
        "decision":        critique.decision,
        "drawdown_flag":   critique.drawdown_flag,
        "notes":           critique.notes,
        "thresholds_used": critique.thresholds_used,
    }


def _summary_payload(update: LedgerUpdate) -> dict[str, Any]:
    return {
        "experiment_id":   update.experiment_id,
        "decision":        update.decision,
        "conclusion":      update.conclusion,
        "lesson_written":  update.lesson_written,
        "lesson_category": update.lesson_category,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(
    cycle_id: str,
    sender: str,
    recipient: str,
    message_type: str,
    payload: dict[str, Any],
    db_path: Path,
) -> None:
    """Log one agent handoff. Silently suppresses errors so the cycle continues."""
    try:
        log_message(cycle_id, sender, recipient, message_type, payload, db_path)
    except Exception:
        log.exception(
            "cycle_runner: failed to log %s→%s (%s) in cycle %s",
            sender, recipient, message_type, cycle_id,
        )


def _next_cycle_id(db_path: Path) -> str:
    """
    Return the next cycle_id as a zero-padded string, e.g. "cycle_003".

    Derived from max(cycle_id) in agent_conversations + 1.
    Returns "cycle_001" if the table is empty.
    """
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT MAX(cycle_id) AS max_id FROM agent_conversations"
            ).fetchone()
            max_id: str | None = row["max_id"] if row else None

        if max_id and max_id.startswith("cycle_"):
            try:
                n = int(max_id.split("_", 1)[1])
                return f"cycle_{n + 1:03d}"
            except ValueError:
                pass
    except Exception:
        log.warning("cycle_runner: could not read max cycle_id — defaulting to cycle_001.")

    return "cycle_001"
