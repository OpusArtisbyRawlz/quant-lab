"""
bar_comparison — a deterministic time-vs-event bar study harness.

Production enablement asks a concrete, *evidence-based* question: on the same
campaigns, do the alternative (event) bars actually improve Sharpe, drawdown,
turnover, and robustness over the time-bar baseline? This module answers it by
running the *identical* backtest pipeline once per bar type and tabulating the
metrics side by side, with signed deltas against a chosen baseline and a simple
per-criterion verdict.

Architectural note
------------------
This harness lives in the executor package but stays **bar-type-agnostic** in
exactly the way the AST guard requires: it never branches on a bar-type literal
and never compares a ``bar_type``-named operand. It simply *iterates* over a
caller-supplied list of bar-type strings, hands each to ``BarEngine.build``, and
keys its results by that string. All sampling logic remains inside the engine;
this module only measures outcomes.

Determinism
-----------
Given the same ``raw_data``, bar-type list, and ``cost_config``, the study is a
pure function of its inputs — every builder is deterministic and the pipeline is
pure — so a study reproduces byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from agents.protocol import ExperimentSpec
from agents.experiment_runner.cost_model import CostConfig
from agents.experiment_runner.runner import _run_pipeline

from src.data.bars import BarEngine, SamplingSpec, align_cross_section


# The metrics we grade, and whether a *larger* value is the better outcome. MDD
# is stored as a drawdown magnitude (>= 0), so smaller is better; turnover
# smaller is better; robustness is measured as a flag *count* (smaller = fewer
# warnings = better). Sharpe larger is better.
_CRITERIA: tuple[tuple[str, bool], ...] = (
    ("sharpe", True),
    ("mdd", False),
    ("turnover", False),
    ("robustness_flags", False),
)


@dataclass(frozen=True)
class BarTypeResult:
    """One row of the study: the graded metrics for a single bar type."""

    bar_type: str
    periods_per_year: float
    sharpe: float | None
    mdd: float | None
    turnover: float | None
    robustness_flags: int
    # Signed change vs the baseline bar type, per graded criterion.
    deltas: dict[str, float] = field(default_factory=dict)
    # Per-criterion verdict vs baseline: "better" / "worse" / "equal".
    verdicts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BarComparison:
    """The full study: one :class:`BarTypeResult` per requested bar type."""

    baseline: str
    results: dict[str, BarTypeResult]

    def improves_over_baseline(self, kind: str) -> bool:
        """True iff ``kind`` is at least as good on every graded criterion and
        strictly better on at least one (a Pareto improvement over baseline)."""
        row = self.results[kind]
        strictly_better_somewhere = False
        for name, _ in _CRITERIA:
            verdict = row.verdicts.get(name, "equal")
            if verdict == "worse":
                return False
            if verdict == "better":
                strictly_better_somewhere = True
        return strictly_better_somewhere

    def to_frame(self) -> pd.DataFrame:
        """Tabular view for reporting: one row per bar type, graded columns."""
        rows = []
        for kind, row in self.results.items():
            rows.append({
                "bar_type": kind,
                "periods_per_year": row.periods_per_year,
                "sharpe": row.sharpe,
                "mdd": row.mdd,
                "turnover": row.turnover,
                "robustness_flags": row.robustness_flags,
                **{f"d_{k}": v for k, v in row.deltas.items()},
            })
        return pd.DataFrame(rows).set_index("bar_type")


def _extract(metrics: dict) -> dict:
    """Pull the graded scalars out of a ``_run_pipeline`` metric bundle."""
    # robustness_flags is a list of triggered-warning names; grade the count
    # (fewer warnings = a more robust strategy).
    flags = metrics.get("robustness_flags") or []
    flag_count = len(flags)
    return {
        "sharpe": metrics.get("sharpe"),
        "mdd": metrics.get("mdd"),
        "turnover": metrics.get("turnover_annualized"),
        "robustness_flags": flag_count,
    }


def _grade(value, base_value, higher_is_better: bool) -> tuple[float, str]:
    """Signed delta and a verdict for one criterion vs the baseline."""
    if value is None or base_value is None:
        return (float("nan"), "equal")
    delta = float(value) - float(base_value)
    if delta == 0.0:
        return (delta, "equal")
    improved = (delta > 0.0) if higher_is_better else (delta < 0.0)
    return (delta, "better" if improved else "worse")


def compare_bar_types(
    raw_data: dict[str, pd.DataFrame],
    spec: ExperimentSpec,
    kinds: list[str],
    *,
    baseline: str = "time",
    cost_config: CostConfig | None = None,
) -> BarComparison:
    """Run ``spec``'s pipeline once per bar type and grade against ``baseline``.

    ``kinds`` is an ordinary list of bar-type strings; ``baseline`` must be
    one of them (defaults to ``"time"``). Each type is sampled through the public
    ``BarEngine.build`` — with ``allow_experimental=True`` so the study can grade
    not-yet-production types — then cross-sectionally aligned and fed through the
    identical backtest pipeline the executor uses. Returns a :class:`BarComparison`.
    """
    if baseline not in kinds:
        raise ValueError(f"baseline {baseline!r} must be among the requested kinds {kinds}")
    cfg = cost_config or CostConfig.load()

    # 1. Sample + run the pipeline for every requested bar type.
    raw_metrics: dict[str, dict] = {}
    ppy: dict[str, float] = {}
    for kind in kinds:
        bar_result = BarEngine.build(
            raw_data, SamplingSpec(type=kind), allow_experimental=True
        )
        aligned = align_cross_section(bar_result.data)
        metrics, _ = _run_pipeline(
            spec, aligned, cfg, periods_per_year=bar_result.periods_per_year
        )
        raw_metrics[kind] = _extract(metrics)
        ppy[kind] = bar_result.periods_per_year

    # 2. Grade each type against the baseline row.
    base = raw_metrics[baseline]
    results: dict[str, BarTypeResult] = {}
    for kind in kinds:
        got = raw_metrics[kind]
        deltas: dict[str, float] = {}
        verdicts: dict[str, str] = {}
        for name, higher_is_better in _CRITERIA:
            delta, verdict = _grade(got[name], base[name], higher_is_better)
            deltas[name] = delta
            verdicts[name] = verdict
        results[kind] = BarTypeResult(
            bar_type=kind,
            periods_per_year=ppy[kind],
            sharpe=got["sharpe"],
            mdd=got["mdd"],
            turnover=got["turnover"],
            robustness_flags=int(got["robustness_flags"]),
            deltas=deltas,
            verdicts=verdicts,
        )

    return BarComparison(baseline=baseline, results=results)
