"""
Ledger Agent — persists the Critic's decision and writes a lesson.

Receives RunResult + CritiqueResult and writes:
  1. decision + conclusion back to the experiments table
  2. One lesson row in lessons_learned

No LLM.  All conclusions are templated from the critique fields.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agents.protocol import CritiqueResult, LedgerUpdate
from agents.experiment_runner.runner import RunResult
from agents.storage.db import DB_PATH
from agents.storage.ledger_store import update_status
from agents.storage.lessons_store import add_lesson

log = logging.getLogger(__name__)

# Category assigned to the lesson based on the critique decision.
_DECISION_TO_CATEGORY: dict[str, str] = {
    "keep":   "signal_quality",
    "reject": "signal_quality",
    "retest": "pipeline",
}

# Confidence assigned based on whether all thresholds passed or only some.
_CONFIDENCE_MAP: dict[tuple[bool, str], str] = {
    (True,  "keep"):   "high",
    (False, "reject"): "high",
    (False, "retest"): "medium",
}


class LedgerAgent:
    """
    Writes the Critic's decision to the database and records a lesson.

    Parameters
    ----------
    None — stateless.
    """

    def run(
        self,
        result: RunResult,
        critique: CritiqueResult,
        db_path: Path = DB_PATH,
    ) -> LedgerUpdate:
        """
        Persist decision and lesson; return a LedgerUpdate receipt.

        Steps
        -----
        1. Build a human-readable conclusion string.
        2. Write decision + conclusion to the experiments table.
        3. Write one lesson to lessons_learned.
        4. Return LedgerUpdate.

        Returns
        -------
        LedgerUpdate
            Always returned; does not raise on storage errors (errors logged).
        """
        conclusion = self._build_conclusion(result, critique)
        category   = _DECISION_TO_CATEGORY.get(critique.decision, "other")
        confidence = _CONFIDENCE_MAP.get(
            (critique.passed, critique.decision), "medium"
        )

        # 1. Write decision + conclusion to experiments table
        lesson_written = False
        status_written = False
        try:
            update_status(
                experiment_id=result.experiment_id,
                status="completed",
                decision=critique.decision,
                next_action=self._next_action(critique.decision),
                db_path=db_path,
            )
            status_written = True
        except Exception:
            log.exception(
                "LedgerAgent: failed to update experiments row for %s",
                result.experiment_id,
            )

        # 2. Write lesson
        try:
            add_lesson(
                experiment_id=result.experiment_id,
                finding=self._build_finding(result, critique),
                implication=self._build_implication(critique),
                category=category,
                confidence=confidence,
                db_path=db_path,
            )
            lesson_written = True
        except Exception:
            log.exception(
                "LedgerAgent: failed to write lesson for %s", result.experiment_id
            )

        log.info(
            "LedgerAgent: %s → decision=%s  lesson_written=%s  category=%s",
            result.experiment_id, critique.decision, lesson_written, category,
        )

        return LedgerUpdate(
            experiment_id  = result.experiment_id,
            decision       = critique.decision,
            conclusion     = conclusion,
            lesson_written = lesson_written,
            lesson_category= category,
            source_idea_id = critique.source_idea_id,
            status_written = status_written,
        )

    # ------------------------------------------------------------------ #
    # Internal — template builders                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_conclusion(result: RunResult, critique: CritiqueResult) -> str:
        sharpe = result.metrics.get("sharpe")
        mdd    = result.metrics.get("mdd")
        decision = critique.decision.upper()

        if result.status == "failed":
            return (
                f"{decision}: pipeline failed for {result.experiment_id}. "
                "No metrics produced. Marked for retest."
            )

        sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "N/A"
        mdd_str    = f"{mdd:.4f}"    if mdd    is not None else "N/A"
        return (
            f"{decision}: {result.experiment_id}  "
            f"Sharpe={sharpe_str}  MDD={mdd_str}.  "
            f"{critique.notes}"
        )

    @staticmethod
    def _build_finding(result: RunResult, critique: CritiqueResult) -> str:
        """Short factual statement for the lessons_learned finding column."""
        if result.status == "failed":
            err_first_line = (result.error or "unknown error").splitlines()[0][:120]
            return f"Pipeline failure for {result.experiment_id}: {err_first_line}"

        sharpe = result.metrics.get("sharpe")
        mdd    = result.metrics.get("mdd")
        sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "N/A"
        mdd_str    = f"{mdd:.4f}"    if mdd    is not None else "N/A"
        return (
            f"Experiment {result.experiment_id}: "
            f"Sharpe={sharpe_str}  MDD={mdd_str}  "
            f"decision={critique.decision}"
        )

    @staticmethod
    def _build_implication(critique: CritiqueResult) -> str:
        """Actionable implication derived from the decision."""
        if critique.decision == "keep":
            return (
                "Strategy passed all active thresholds. "
                "Consider combining with complementary signals or promoting to library."
            )
        if critique.decision == "reject":
            return (
                "Strategy failed one or more thresholds. "
                "Avoid this signal combination in this universe without modification."
            )
        # retest
        return (
            "Pipeline error — not a signal failure. "
            "Check data quality and pipeline configuration before retrying."
        )

    @staticmethod
    def _next_action(decision: str) -> str:
        return {
            "keep":   "promote_or_combine",
            "reject": "archive",
            "retest": "retest",
        }.get(decision, "review")
