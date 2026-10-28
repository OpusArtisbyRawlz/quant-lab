"""
Statistical-integrity report assembly for Project 07.

Aggregates the outputs of the individual tests (bootstrap intervals, Monte-Carlo
p-values, multiple-testing corrections, Deflated Sharpe, Reality Check / SPA) into
a single per-strategy verdict, and renders the consolidated report consumed by
notebook ``06_statistical_report.ipynb``.

The verdict is a **conjunction of gates**, not a weighted score: a strategy is
statistically supported only if it clears every applicable test. This mirrors the
gate philosophy used elsewhere in the repo and prevents one strong result from
masking a failure on another axis.

Scaffold only — all bodies raise ``NotImplementedError``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.statistics.evidence import Decision, EvidenceRecord


@dataclass(frozen=True)
class IntegrityVerdict:
    """Consolidated statistical-integrity verdict for one strategy.

    Attributes
    ----------
    strategy_version
        The strategy the verdict applies to.
    decision
        The overall :class:`~src.statistics.evidence.Decision`.
    gates_passed
        Mapping of gate name → pass/fail (e.g. ``{"deflated_sharpe": True, ...}``).
    supporting_records
        Evidence-ledger record ids that back the verdict.
    rationale
        Human-readable explanation of the decision.
    """

    strategy_version: str
    decision: Decision
    gates_passed: dict[str, bool]
    supporting_records: list[str]
    rationale: str


def build_report(records: list[EvidenceRecord]) -> pd.DataFrame:
    """Assemble a tabular statistical-integrity report from evidence records.

    Parameters
    ----------
    records
        Evidence-ledger records for the strategy/strategies under review.

    Returns
    -------
    pandas.DataFrame
        One row per (strategy, test) with statistic, p-value, interval and
        decision, suitable for display and CSV export.
    """
    raise NotImplementedError("report assembly not implemented (scaffold).")


def summarize_verdict(
    records: list[EvidenceRecord],
    *,
    strategy_version: str,
) -> IntegrityVerdict:
    """Reduce a strategy's evidence records to a single gated verdict.

    Parameters
    ----------
    records
        Evidence-ledger records for the strategy.
    strategy_version
        The strategy to summarise.

    Returns
    -------
    IntegrityVerdict
        The conjunction-of-gates decision and its rationale.
    """
    raise NotImplementedError("verdict summarisation not implemented (scaffold).")


def render_report(
    report: pd.DataFrame,
    *,
    output_path: Optional[str] = None,
) -> str:
    """Render the report table to markdown (optionally writing to ``output_path``).

    Parameters
    ----------
    report
        The report frame from :func:`build_report`.
    output_path
        If given, the markdown is also written to this path.

    Returns
    -------
    str
        The rendered markdown.
    """
    raise NotImplementedError("report rendering not implemented (scaffold).")
