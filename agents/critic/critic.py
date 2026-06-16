"""
Critic — rule-based experiment evaluator.

Receives a RunResult and ExperimentSpec.  Resolves thresholds from
the spec's success_criteria (high priority) falling back to
agents/config/critic_defaults.toml (low priority).  Returns a
CritiqueResult with a decision: keep / reject / retest.

No LLM.  No global constants.  Thresholds come only from the two
approved sources above.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agents.protocol import CritiqueResult, ExperimentSpec
from agents.experiment_runner.runner import RunResult
from agents.critic.thresholds import CriticThresholds

log = logging.getLogger(__name__)


class Critic:
    """
    Rule-based experiment critic.

    Parameters
    ----------
    config_path : Path, optional
        Path to a TOML file with default thresholds.  Defaults to
        agents/config/critic_defaults.toml.  Override in tests to inject
        custom thresholds without touching the checked-in config file.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._defaults = CriticThresholds.load_defaults(config_path)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def run(self, result: RunResult, spec: ExperimentSpec) -> CritiqueResult:
        """
        Evaluate a RunResult against the spec's success criteria.

        Decision logic
        --------------
        - RunResult.status == "failed"  →  "retest"  (pipeline error, not a bad signal)
        - All active thresholds pass    →  "keep"
        - Any active threshold fails    →  "reject"   (under "strict" policy)
        - Majority pass                 →  "keep"     (under "majority" policy)

        Returns
        -------
        CritiqueResult
            Always returned; check .decision and .passed.
        """
        thresholds = self._defaults.merge(spec.success_criteria)

        # ── Handle pipeline failure before touching metrics ────────────────
        if result.status == "failed":
            log.info("Critic: %s → retest (pipeline failed)", result.experiment_id)
            return CritiqueResult(
                experiment_id=result.experiment_id,
                passed=False,
                drawdown_flag=False,
                decision="retest",
                notes="Pipeline failed — no metrics produced. Marked for retest.",
                thresholds_used=thresholds.as_log_dict(),
            )

        # ── Evaluate each active threshold ─────────────────────────────────
        checks = self._evaluate(result.metrics, thresholds)
        drawdown_flag = self._is_drawdown_flag(result.metrics, thresholds)

        # ── Apply decision policy ──────────────────────────────────────────
        decision, passed = self._apply_policy(checks, thresholds.policy)

        notes = self._format_notes(checks, result.metrics, thresholds)
        log.info(
            "Critic: %s → %s  (sharpe=%.3f  mdd=%.3f  checks=%s)",
            result.experiment_id,
            decision,
            result.metrics.get("sharpe") or float("nan"),
            result.metrics.get("mdd") or float("nan"),
            checks,
        )

        return CritiqueResult(
            experiment_id=result.experiment_id,
            passed=passed,
            drawdown_flag=drawdown_flag,
            decision=decision,
            notes=notes,
            thresholds_used=thresholds.as_log_dict(),
        )

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _evaluate(
        metrics: dict,
        thresholds: CriticThresholds,
    ) -> dict[str, bool]:
        """
        Return {check_name: passed} for every active threshold.

        A threshold is "active" when its value is not None.
        Metrics that are None (computation failed) count as a failure.
        """
        checks: dict[str, bool] = {}

        def _check_min(key: str, threshold: float | None, metric_key: str) -> None:
            if threshold is None:
                return
            val = metrics.get(metric_key)
            checks[key] = (val is not None) and (val >= threshold)

        def _check_max_loss(key: str, threshold: float | None, metric_key: str) -> None:
            """MDD threshold: mdd must be >= threshold (e.g. >= -0.40)."""
            if threshold is None:
                return
            val = metrics.get(metric_key)
            checks[key] = (val is not None) and (val >= threshold)

        _check_min("minimum_sharpe",  thresholds.minimum_sharpe,  "sharpe")
        _check_max_loss("maximum_mdd", thresholds.maximum_mdd,    "mdd")
        _check_min("minimum_calmar",  thresholds.minimum_calmar,  "calmar")
        _check_min("minimum_cagr",    thresholds.minimum_cagr,    "cagr")

        return checks

    @staticmethod
    def _is_drawdown_flag(metrics: dict, thresholds: CriticThresholds) -> bool:
        """True when mdd breaches the maximum_mdd threshold."""
        if thresholds.maximum_mdd is None:
            return False
        mdd = metrics.get("mdd")
        return mdd is not None and mdd < thresholds.maximum_mdd

    @staticmethod
    def _apply_policy(
        checks: dict[str, bool],
        policy: str,
    ) -> tuple[str, bool]:
        """Apply strict or majority policy. Returns (decision, passed)."""
        if not checks:
            # No active thresholds — pass with a note
            return "keep", True

        if policy == "strict":
            passed = all(checks.values())
        elif policy == "majority":
            passed = sum(checks.values()) > len(checks) / 2
        else:
            log.warning("Unknown decision policy %r — defaulting to strict.", policy)
            passed = all(checks.values())

        return ("keep" if passed else "reject"), passed

    @staticmethod
    def _format_notes(
        checks: dict[str, bool],
        metrics: dict,
        thresholds: CriticThresholds,
    ) -> str:
        """Human-readable evaluation notes for storage and logging."""
        lines: list[str] = []

        _metric_labels = {
            "minimum_sharpe": ("sharpe",  "Sharpe",  "≥"),
            "maximum_mdd":    ("mdd",     "MDD",     "≥"),
            "minimum_calmar": ("calmar",  "Calmar",  "≥"),
            "minimum_cagr":   ("cagr",    "CAGR",    "≥"),
        }

        for check_key, passed in checks.items():
            metric_key, label, direction = _metric_labels[check_key]
            actual = metrics.get(metric_key)
            threshold_attr = check_key  # same name
            threshold_val = getattr(thresholds, threshold_attr)
            source = thresholds.sources.get(threshold_attr, "?")
            actual_str = f"{actual:.4f}" if actual is not None else "None"
            threshold_str = f"{threshold_val:.4f}" if threshold_val is not None else "None"
            status = "✓" if passed else "✗"
            lines.append(
                f"{status} {label}: actual={actual_str}  "
                f"threshold={direction}{threshold_str} [{source}]"
            )

        return "\n".join(lines) if lines else "No thresholds evaluated."
