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
    outcome: str                       # executed / rejected
    experiment_id: str | None = None
    decision: str | None = None        # critic decision when executed
    reasons: list[str] = field(default_factory=list)  # rejection reasons


@dataclass
class ExecutionBatchOutcome:
    executed: list[IdeaExecutionResult] = field(default_factory=list)
    rejected: list[IdeaExecutionResult] = field(default_factory=list)


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
        reasons = _classify_validation_errors(vr.errors)
        approval_queue.reject_approved(idea_id, note="; ".join(reasons), db_path=db_path)
        _log_exec_rejected(idea_row, reasons, db_path=db_path)
        return IdeaExecutionResult(idea_id=idea_id, outcome="rejected", reasons=reasons)

    # --- Execute through the UNCHANGED M5 pipeline ---
    result: RunResult = run_experiment(
        spec,
        db_path=db_path,
        completed_dir=completed_dir,
        data_root=data_root,
        data_dict=data_dict,
        cost_config=cost_config,
    )

    # --- Critic (net + robustness) and Ledger (decision + lesson), unchanged ---
    critique = critic.run(result, spec, source_idea_id=idea_id)
    ledger.run(result, critique, db_path=db_path)

    # --- Stamp provenance onto the experiment row (idea -> experiment, model) ---
    if result.experiment_id and result.status in ("success", "failed"):
        upsert_experiment(
            {
                "experiment_id": result.experiment_id,
                "source_idea_id": idea_id,
                "source_model": idea_row.get("source_model", ""),
            },
            db_path=db_path,
        )
        approval_queue.mark_executed(idea_id, result.experiment_id, db_path=db_path)
        _log_executed(idea_row, result, critique.decision, db_path=db_path)
        return IdeaExecutionResult(
            idea_id=idea_id, outcome="executed",
            experiment_id=result.experiment_id, decision=critique.decision,
        )

    # invalid_spec slipping through pre-validation (defensive) -> reject.
    reasons = _classify_validation_errors([result.error or "spec_invalid_after_revalidation"])
    approval_queue.reject_approved(idea_id, note="; ".join(reasons), db_path=db_path)
    _log_exec_rejected(idea_row, reasons, db_path=db_path)
    return IdeaExecutionResult(idea_id=idea_id, outcome="rejected", reasons=reasons)


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
    approved = approval_queue.list_approved(db_path=db_path)
    if limit is not None:
        approved = approved[:limit]

    batch = ExecutionBatchOutcome()
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
            db_path=db_path,
        )
        (batch.executed if res.outcome == "executed" else batch.rejected).append(res)
    return batch


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

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
