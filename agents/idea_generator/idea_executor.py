"""
idea_executor.py — M7 bridge: approved idea -> experiment -> critic -> ledger.

This is the consumer that M6 deliberately omitted. It drains ideas with
status='approved', converts each to an ExperimentSpec, re-validates against
REAL data (resolving TD-7), runs the UNCHANGED M5 pipeline, has the existing
Critic judge on net+robustness, the existing Ledger record decision+lesson,
stamps idea/model provenance onto the experiment row, and transitions the idea
to 'executed' with its experiment_id linked.

Invariants (enforced here):
- Execution is ONLY invoked explicitly via these functions — never auto-fired
  by approval.
- One approved idea -> one spec -> one experiment. No expansion/combination.
- Idempotent/resumable: only 'approved' rows are drained; each is flipped to
  'executed' (or 'rejected' on execution-time validation failure), so a re-run
  never double-processes.
- No retries, no scheduler, no loops, no signal-library promotion, no CLI.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from agents.protocol import ExperimentSpec
from agents.storage.db import DB_PATH
from agents.storage.conversation_store import log_message
from agents.storage.ledger_store import upsert_experiment
from agents.experiment_runner.runner import (
    run_experiment,
    RunResult,
    COMPLETED_DIR,
    DATA_ROOT,
)
from agents.experiment_runner.spec_validator import validate_spec
from agents.experiment_runner.cost_model import CostConfig
from agents.critic.critic import Critic
from agents.ledger_agent.ledger_agent import LedgerAgent
from agents.quant_interface.artifact_reader import read_experiment_artifact
from agents.signal_librarian.librarian import SignalLibrarian

from . import approval_queue, scoring
from .spec_builder import idea_to_spec

log = logging.getLogger(__name__)

_SENDER = "idea_executor"

# Provider: given a spec, return a pre-loaded data_dict (testing seam). When
# None, run_experiment loads from disk under data_root — the production path.
DataDictProvider = Callable[[ExperimentSpec], "dict[str, pd.DataFrame]"]


@dataclass
class IdeaExecutionResult:
    idea_id: str
    outcome: str                       # executed / rejected / error
    experiment_id: str | None = None
    decision: str | None = None        # critic decision when executed
    reasons: list[str] = field(default_factory=list)  # rejection / error reasons


@dataclass
class ExecutionBatchOutcome:
    executed: list[IdeaExecutionResult] = field(default_factory=list)
    rejected: list[IdeaExecutionResult] = field(default_factory=list)
    errored: list[IdeaExecutionResult] = field(default_factory=list)


@dataclass
class RecoveryOutcome:
    recovered: list[IdeaExecutionResult] = field(default_factory=list)
    still_incomplete: list[IdeaExecutionResult] = field(default_factory=list)


def run_single_approved_idea(
    idea_id: str,
    *,
    data_root: Path = DATA_ROOT,
    completed_dir: Path = COMPLETED_DIR,
    data_dict_provider: DataDictProvider | None = None,
    cost_config: CostConfig | None = None,
    success_criteria: dict | None = None,
    critic: Critic | None = None,
    ledger: LedgerAgent | None = None,
    librarian: SignalLibrarian | None = None,
    db_path: Path = DB_PATH,
) -> IdeaExecutionResult:
    """
    Execute one approved idea by id. Returns an IdeaExecutionResult. If the idea
    is not in 'approved' status, returns a rejection with reason 'not_approved'
    (no side effects).
    """
    idea_row = approval_queue.get_approved(idea_id, db_path=db_path)
    if idea_row is None:
        return IdeaExecutionResult(idea_id=idea_id, outcome="rejected",
                                   reasons=["not_approved"])

    critic = critic or Critic()
    ledger = ledger or LedgerAgent()
    librarian = librarian or SignalLibrarian()

    spec = idea_to_spec(idea_row, success_criteria=success_criteria)

    # --- Re-validate against REAL data (TD-7). Skip the disk check only when a
    #     data_dict is supplied (tests), exactly as run_experiment does. ---
    data_dict = data_dict_provider(spec) if data_dict_provider else None
    vr = validate_spec(
        spec,
        data_root=data_root,
        completed_dir=completed_dir,
        skip_data_check=(data_dict is not None),
    )
    if not vr.valid:
        # Validation has no side effects, so we reject from `approved` BEFORE
        # claiming — an infeasible idea never enters the executing state.
        reasons = _classify_validation_errors(vr.errors)
        approval_queue.reject_approved(idea_id, note="; ".join(reasons), db_path=db_path)
        _log_exec_rejected(idea_row, reasons, db_path=db_path)
        return IdeaExecutionResult(idea_id=idea_id, outcome="rejected", reasons=reasons)

    # --- R2: atomically claim the idea (approved -> executing). If we lose the
    #     claim, a concurrent executor already owns it; do nothing. ---
    if not approval_queue.claim_for_execution(idea_id, db_path=db_path):
        return IdeaExecutionResult(idea_id=idea_id, outcome="error",
                                   reasons=["already_claimed"])

    # --- Execute through the UNCHANGED M5 pipeline ---
    result: RunResult = run_experiment(
        spec,
        db_path=db_path,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=data_dict,
        cost_config=cost_config,
    )

    # invalid_spec slipping through pre-validation (defensive) -> reject from
    # the executing state.
    if not (result.experiment_id and result.status in ("success", "failed")):
        reasons = _classify_validation_errors(
            [result.error or "spec_invalid_after_revalidation"])
        approval_queue.reject_executing(idea_id, note="; ".join(reasons), db_path=db_path)
        _log_exec_rejected(idea_row, reasons, db_path=db_path)
        return IdeaExecutionResult(idea_id=idea_id, outcome="rejected", reasons=reasons)

    # --- R3: stamp provenance + link experiment_id NOW, before Critic/Ledger,
    #     so the experiment is never an orphan and the lesson is always
    #     attributable to the idea. Status stays `executing`. ---
    upsert_experiment(
        {
            "experiment_id": result.experiment_id,
            "source_idea_id": idea_id,
            "source_model": idea_row.get("source_model", ""),
            # M9: stamp the research context so the experiment row is
            # self-describing and the SignalLibrarian can decompose it into
            # context cells (feature x market x universe x regime x bar_type).
            "market": spec.market,
            "universe": spec.universe,
            "features": json.dumps(list(spec.features)),
        },
        db_path=db_path,
    )
    approval_queue.link_experiment(idea_id, result.experiment_id, db_path=db_path)

    # --- Critic (net + robustness) and Ledger (decision + lesson), unchanged ---
    critique = critic.run(result, spec, source_idea_id=idea_id)
    ledger_update = ledger.run(result, critique, db_path=db_path)

    # --- R1: completion is gated on a confirmed ledger write. If persistence
    #     failed, leave the idea in `executing` (recoverable) and surface the
    #     error — never mark it executed with a missing decision/lesson. ---
    if not ledger_update.ok:
        _log_exec_incomplete(idea_row, result, ledger_update, db_path=db_path)
        return IdeaExecutionResult(
            idea_id=idea_id, outcome="error",
            experiment_id=result.experiment_id, decision=critique.decision,
            reasons=["ledger_write_failed"],
        )

    approval_queue.mark_executed(idea_id, result.experiment_id, db_path=db_path)
    _log_executed(idea_row, result, critique.decision, db_path=db_path)

    # --- M9: post-Ledger context-aware signal intelligence. Fully isolated —
    #     a librarian failure must never undo a completed, ledgered execution. ---
    _record_to_librarian(librarian, result.experiment_id, db_path=db_path)

    return IdeaExecutionResult(
        idea_id=idea_id, outcome="executed",
        experiment_id=result.experiment_id, decision=critique.decision,
    )


def run_approved_ideas(
    *,
    data_root: Path = DATA_ROOT,
    completed_dir: Path = COMPLETED_DIR,
    data_dict_provider: DataDictProvider | None = None,
    cost_config: CostConfig | None = None,
    success_criteria: dict | None = None,
    limit: int | None = None,
    db_path: Path = DB_PATH,
) -> ExecutionBatchOutcome:
    """
    Drain approved ideas and execute each. Explicit invocation only — never
    triggered by approval. `limit` caps how many are processed this run.
    """
    critic = Critic()
    ledger = LedgerAgent()
    librarian = SignalLibrarian()
    approved = approval_queue.list_approved(db_path=db_path)
    if limit is not None:
        approved = approved[:limit]

    batch = ExecutionBatchOutcome()
    _bucket = {"executed": batch.executed, "rejected": batch.rejected,
               "error": batch.errored}
    for idea_row in approved:
        res = run_single_approved_idea(
            idea_row["idea_id"],
            data_root=data_root,
            completed_dir=completed_dir,
            data_dict_provider=data_dict_provider,
            cost_config=cost_config,
            success_criteria=success_criteria,
            critic=critic,
            ledger=ledger,
            librarian=librarian,
            db_path=db_path,
        )
        _bucket.get(res.outcome, batch.errored).append(res)
    return batch


def recover_incomplete_executions(
    *,
    completed_dir: Path = COMPLETED_DIR,
    success_criteria: dict | None = None,
    critic: Critic | None = None,
    ledger: LedgerAgent | None = None,
    db_path: Path = DB_PATH,
) -> RecoveryOutcome:
    """
    Repair ideas left in `executing` by a failed ledger write (R1 recovery).

    For each stuck idea that already has a linked experiment_id, the experiment
    and its artifacts already exist — so we do NOT re-run the pipeline (that
    would create a duplicate experiment). Instead we reconstruct the RunResult
    from the stored artifacts and re-run the deterministic Critic + Ledger. On a
    confirmed ledger write the idea is completed (`executing -> executed`);
    otherwise it is left `executing` for the next recovery attempt.

    An executing idea WITHOUT a linked experiment_id cannot be recovered here
    (it failed before the experiment was created); it is reported as
    still-incomplete for manual inspection rather than silently re-run.
    """
    critic = critic or Critic()
    ledger = ledger or LedgerAgent()

    out = RecoveryOutcome()
    for idea_row in approval_queue.list_executing(db_path=db_path):
        idea_id = idea_row["idea_id"]
        experiment_id = idea_row.get("experiment_id")
        if not experiment_id:
            out.still_incomplete.append(IdeaExecutionResult(
                idea_id=idea_id, outcome="error",
                reasons=["no_linked_experiment"]))
            continue

        result = _reconstruct_run_result(experiment_id, completed_dir)
        spec = idea_to_spec(idea_row, success_criteria=success_criteria)
        critique = critic.run(result, spec, source_idea_id=idea_id)
        ledger_update = ledger.run(result, critique, db_path=db_path)

        if not ledger_update.ok:
            _log_exec_incomplete(idea_row, result, ledger_update, db_path=db_path)
            out.still_incomplete.append(IdeaExecutionResult(
                idea_id=idea_id, outcome="error",
                experiment_id=experiment_id, reasons=["ledger_write_failed"]))
            continue

        approval_queue.mark_executed(idea_id, experiment_id, db_path=db_path)
        _log_executed(idea_row, result, critique.decision, db_path=db_path)
        out.recovered.append(IdeaExecutionResult(
            idea_id=idea_id, outcome="executed",
            experiment_id=experiment_id, decision=critique.decision))
    return out


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _record_to_librarian(librarian: SignalLibrarian, experiment_id: str,
                         *, db_path: Path) -> None:
    """Feed a completed experiment to the SignalLibrarian, isolated from the
    execution outcome. Any failure is logged and swallowed: M9 knowledge-keeping
    is strictly downstream of — and must never roll back — a ledgered run."""
    try:
        librarian.record_experiment(experiment_id, db_path=db_path)
    except Exception:
        log.exception(
            "idea_executor: SignalLibrarian failed for %s (execution already "
            "complete; context knowledge not updated)", experiment_id,
        )


def _reconstruct_run_result(experiment_id: str, completed_dir: Path) -> RunResult:
    """
    Rebuild a RunResult from stored artifacts for recovery, WITHOUT re-running
    the pipeline. metrics.json carries the full metric dict (gross + net +
    robustness_flags), so Critic/Ledger see exactly what they saw originally.
    A missing metrics.json means the original run failed before writing them →
    reconstruct as a 'failed' result so the Critic returns 'retest'.
    """
    folder = completed_dir / experiment_id
    bundle = read_experiment_artifact(folder)
    if bundle.metrics:
        return RunResult(
            experiment_id=experiment_id,
            status="success",
            metrics=bundle.metrics,
            artifact_path=folder,
        )
    return RunResult(
        experiment_id=experiment_id,
        status="failed",
        artifact_path=folder,
        error="metrics.json missing — original pipeline run failed",
    )


def _classify_validation_errors(errors: list[str]) -> list[str]:
    """Map validate_spec / runner errors to explicit M7 rejection reason codes."""
    reasons: list[str] = []
    joined = " ".join(errors).lower()
    if "universe data directory not found" in joined or "no csv files" in joined \
            or "no data loaded" in joined:
        reasons.append("universe_data_missing")
    if "unknown signal" in joined:
        reasons.append("signal_unavailable")
    if not reasons:
        reasons.append("spec_invalid_after_revalidation")
    return reasons


def _log_executed(idea_row: dict, result: RunResult, decision: str,
                  *, db_path: Path) -> None:
    log_message(
        idea_row.get("cycle_id") or "manual", _SENDER, "ledger_agent", "idea_executed",
        {
            "idea_id": idea_row["idea_id"],
            "experiment_id": result.experiment_id,
            "source_model": idea_row.get("source_model", ""),
            "decision": decision,
            "net_sharpe": (result.metrics.get("net") or {}).get("sharpe"),
            "net_calmar": (result.metrics.get("net") or {}).get("calmar"),
            "robustness_flags": result.metrics.get("robustness_flags") or [],
        },
        db_path=db_path,
    )


def _log_exec_incomplete(idea_row: dict, result: RunResult, ledger_update,
                         *, db_path: Path) -> None:
    """Surface a stuck (executing) idea: the experiment exists but the ledger
    write did not complete, so the idea is recoverable, not executed."""
    log_message(
        idea_row.get("cycle_id") or "manual", _SENDER, "system",
        "idea_execution_incomplete",
        {
            "idea_id": idea_row["idea_id"],
            "experiment_id": result.experiment_id,
            "source_model": idea_row.get("source_model", ""),
            "stage": "ledger_write",
            "status_written": ledger_update.status_written,
            "lesson_written": ledger_update.lesson_written,
            "recoverable": True,
        },
        db_path=db_path,
    )


def _log_exec_rejected(idea_row: dict, reasons: list[str], *, db_path: Path) -> None:
    log_message(
        idea_row.get("cycle_id") or "manual", _SENDER, "system", "idea_rejected",
        {
            "idea_id": idea_row["idea_id"],
            "source_model": idea_row.get("source_model", ""),
            "stage": "execution_validation",
            "validation": {"ok": False, "reasons": reasons},
        },
        db_path=db_path,
    )
