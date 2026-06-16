"""
Experiment Designer — converts a HypothesisTask into a fully-formed
ExperimentSpec ready for the Runner.

Logic (no LLM):
  1. Use task.suggested_signals if they are all known; otherwise fall back
     to a default signal set appropriate for the hypothesis type.
  2. Fill in standard fields: model, target, validation_method.
  3. Consult lessons_learned to avoid known-bad signal/universe combos.
  4. Validate the spec with spec_validator; raise DesignError if invalid.

No LLM, no external calls. All logic is deterministic and rule-based.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agents.protocol import ExperimentSpec, HypothesisTask
from agents.storage.db import DB_PATH
from agents.storage.lessons_store import list_lessons
from agents.experiment_runner.spec_validator import KNOWN_SIGNALS, validate_spec

log = logging.getLogger(__name__)

# Default signal sets used when the hypothesis doesn't clearly name signals.
# Ordered from most specific to most general.
_DEFAULT_SIGNALS: list[list[str]] = [
    ["mr_ret_5"],
    ["mr_ret_10"],
    ["low_vol_20"],
    ["mom_ret_10"],
]

_DEFAULT_MODEL             = "quantile_ranking"
_DEFAULT_TARGET            = "fwd_ret_5"
_DEFAULT_VALIDATION_METHOD = "walk_forward"
_DEFAULT_SUCCESS_CRITERIA  = {"sharpe": 0.5}


class DesignError(Exception):
    """Raised when the Designer cannot produce a valid ExperimentSpec."""


class ExperimentDesigner:
    """
    Rule-based experiment designer.

    Parameters
    ----------
    None — stateless; context loaded from the DB at run time.
    """

    def run(
        self,
        task: HypothesisTask,
        db_path: Path = DB_PATH,
        data_root: Path | None = None,
    ) -> ExperimentSpec:
        """
        Convert a HypothesisTask into an ExperimentSpec.

        Steps
        -----
        1. Resolve the signal list (task hints → lessons filter → default).
        2. Build a candidate ExperimentSpec with standard field values.
        3. Validate; raise DesignError if spec_validator reports errors.

        Returns
        -------
        ExperimentSpec
            Fully-populated and validated spec.

        Raises
        ------
        DesignError
            If no valid signal set can be found, or spec validation fails.
        """
        avoided = self._load_avoided_signals(task, db_path)
        signals = self._resolve_signals(task, avoided)

        spec = ExperimentSpec(
            hypothesis        = task.hypothesis,
            market            = task.market,
            universe          = task.universe,
            target            = _DEFAULT_TARGET,
            features          = signals,
            model             = _DEFAULT_MODEL,
            validation_method = _DEFAULT_VALIDATION_METHOD,
            success_criteria  = _DEFAULT_SUCCESS_CRITERIA,
            expected_improvement = "Positive Sharpe vs. random",
            project           = task.project,
        )

        # Validate — skip data-dir check because the cycle runner will supply
        # data_dict (testing seam) or load it separately.
        validation = validate_spec(
            spec,
            data_root=data_root or Path("."),
            skip_data_check=True,
        )
        if not validation.valid:
            raise DesignError(
                f"Designer could not produce a valid spec for hypothesis "
                f"{task.hypothesis!r}: {'; '.join(validation.errors)}"
            )

        if validation.warnings:
            for w in validation.warnings:
                log.warning("Designer spec warning: %s", w)

        log.info(
            "Designer: spec ready — features=%s  model=%s  universe=%s",
            spec.features, spec.model, spec.universe,
        )
        return spec

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_avoided_signals(task: HypothesisTask, db_path: Path) -> set[str]:
        """
        Read lessons_learned for reject-category entries in this universe.
        Extracts signal names from lesson findings so the Designer can avoid
        known-bad combinations.
        """
        avoided: set[str] = set()
        try:
            lessons = list_lessons(
                category="signal_quality",
                confidence="high",
                db_path=db_path,
            )
        except Exception:
            log.warning("Designer: could not load lessons — no signals avoided.")
            return avoided

        for lesson in lessons:
            finding = (lesson.get("finding") or "").lower()
            # Very simple extraction: if a known signal name appears in a
            # "reject" lesson, add it to the avoided set.
            if "reject" in finding or "fail" in finding:
                for sig in KNOWN_SIGNALS:
                    if sig in finding:
                        avoided.add(sig)

        if avoided:
            log.info("Designer: avoiding signals from lessons: %s", avoided)
        return avoided

    @staticmethod
    def _resolve_signals(
        task: HypothesisTask,
        avoided: set[str],
    ) -> list[str]:
        """
        Return the signal list to use for this task.

        Priority:
          1. task.suggested_signals — if all are known and none avoided → use as-is
          2. task.suggested_signals filtered to remove avoided signals — if non-empty
          3. First default signal set that contains no avoided signals
          4. First default signal set regardless (last resort)

        Raises
        ------
        DesignError
            If no candidate signals remain after all filtering.
        """
        # Validate suggested signals
        valid_suggested = [s for s in task.suggested_signals if s in KNOWN_SIGNALS]
        clean_suggested = [s for s in valid_suggested if s not in avoided]

        if clean_suggested:
            return clean_suggested

        if valid_suggested:
            # Some suggested signals exist but all are avoided — warn and use them anyway
            log.warning(
                "Designer: all suggested signals %s are in the avoided set %s — "
                "using them anyway (no alternative).",
                valid_suggested, avoided,
            )
            return valid_suggested

        # No usable suggested signals — try defaults
        for default_set in _DEFAULT_SIGNALS:
            if not any(s in avoided for s in default_set):
                log.info(
                    "Designer: no suggested signals for hypothesis; "
                    "falling back to default set %s.",
                    default_set,
                )
                return default_set

        # Last resort: use first default regardless
        log.warning(
            "Designer: all default signal sets overlap with avoided set %s — "
            "using first default anyway.",
            avoided,
        )
        return _DEFAULT_SIGNALS[0]
