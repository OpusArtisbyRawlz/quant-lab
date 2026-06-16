"""
Commander — prioritises and filters the research agenda.

Receives a ResearchAgenda (externally provided hypotheses) and returns an
ordered list of HypothesisTasks for the Experiment Designer to execute.

Logic (no LLM):
  1. Query the ledger for experiments already run in this project/universe.
  2. Skip hypotheses whose (hypothesis text, suggested signals) pair has
     already been attempted — avoids exact re-runs.
  3. Return the remainder sorted by priority (descending).

This is Milestone 4 scope: no idea generation, no LLM, no auto-expansion
of the agenda. The hypothesis list comes entirely from the caller.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agents.protocol import HypothesisTask, ResearchAgenda
from agents.storage.db import DB_PATH
from agents.storage.ledger_store import list_experiments

log = logging.getLogger(__name__)


class Commander:
    """
    Rule-based commander that prioritises and deduplicates the research agenda.

    Parameters
    ----------
    None — stateless; all context is loaded from the DB at run time.
    """

    def run(
        self,
        agenda: ResearchAgenda,
        db_path: Path = DB_PATH,
    ) -> list[HypothesisTask]:
        """
        Convert a ResearchAgenda into an ordered list of HypothesisTasks.

        Steps
        -----
        1. Build tasks from agenda.hypotheses (one task per hypothesis).
           Suggested signals are extracted from the hypothesis text using
           a simple keyword scan against KNOWN_SIGNALS (good enough for M4;
           an LLM step can replace this in a later milestone).
        2. Filter out tasks that exactly duplicate a past run in the same
           project × universe.
        3. Sort by priority descending (higher = first).

        Returns
        -------
        list[HypothesisTask]
            May be empty if all hypotheses were already attempted.
        """
        tasks = self._build_tasks(agenda)
        tasks = self._filter_duplicates(tasks, agenda, db_path)
        tasks.sort(key=lambda t: t.priority, reverse=True)

        log.info(
            "Commander: %d/%d hypotheses queued after dedup (project=%s universe=%s)",
            len(tasks),
            len(agenda.hypotheses),
            agenda.project,
            agenda.universe,
        )
        return tasks

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_tasks(agenda: ResearchAgenda) -> list[HypothesisTask]:
        """
        One HypothesisTask per hypothesis string.

        Suggested signals are extracted by scanning hypothesis text for
        substrings that match known signal names.  The Experiment Designer
        may override them entirely.
        """
        from agents.experiment_runner.spec_validator import KNOWN_SIGNALS

        tasks: list[HypothesisTask] = []
        for idx, hypothesis in enumerate(agenda.hypotheses):
            lower = hypothesis.lower()
            suggested = [s for s in sorted(KNOWN_SIGNALS) if s.replace("_", " ") in lower or s in lower]
            tasks.append(HypothesisTask(
                hypothesis=hypothesis,
                suggested_signals=suggested,
                project=agenda.project,
                universe=agenda.universe,
                market=agenda.market,
                priority=len(agenda.hypotheses) - idx,  # earlier = higher priority
            ))
        return tasks

    @staticmethod
    def _filter_duplicates(
        tasks: list[HypothesisTask],
        agenda: ResearchAgenda,
        db_path: Path,
    ) -> list[HypothesisTask]:
        """
        Remove tasks that have already been run in this project × universe.

        Match criterion: hypothesis text is identical (case-insensitive).
        This is intentionally loose — the Designer controls the actual spec.
        """
        try:
            past = list_experiments(db_path=db_path)
        except Exception:
            log.warning("Commander: could not read ledger — skipping duplicate check.")
            return tasks

        past_hypotheses: set[str] = {
            (r.get("hypothesis") or "").strip().lower()
            for r in past
            if r.get("project") == agenda.project
            and r.get("universe") == agenda.universe
        }

        unique = [
            t for t in tasks
            if t.hypothesis.strip().lower() not in past_hypotheses
        ]

        skipped = len(tasks) - len(unique)
        if skipped:
            log.info("Commander: skipped %d already-attempted hypothesis(es).", skipped)

        return unique
