"""
idea_validator.py — the deterministic gate between LLM proposal and the queue.

Every check is rule-based and returns explicit reasons; there are no silent
failures. An idea is enqueued as `pending` only if it passes ALL checks:

- every suggested signal is in KNOWN_SIGNALS
- the hypothesis is non-empty
- the signal list is non-empty
- the idea is NOT a duplicate of an existing experiment hypothesis, a
  lessons_learned finding, or a previously proposed/approved idea
- a minimal ExperimentSpec built from the idea passes validate_spec()

Advisory scores are intentionally ignored here — they never gate validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agents.protocol import ExperimentSpec, ProposedIdea
from agents.experiment_runner.spec_validator import (
    KNOWN_SIGNALS,
    validate_spec,
)

# Mirror the designer's spec defaults so feasibility-checking an idea matches
# how a real spec would later be built.
_DEFAULT_MODEL = "quantile_ranking"
_DEFAULT_TARGET = "fwd_ret_5"
_DEFAULT_VALIDATION_METHOD = "walk_forward"
_DEFAULT_SUCCESS_CRITERIA = {"sharpe": 0.5}


@dataclass
class IdeaValidationResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)  # populated only when ok is False


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def validate_idea(
    idea: ProposedIdea,
    *,
    existing_hypotheses: set[str],
    lesson_findings: set[str],
    prior_idea_hypotheses: set[str],
    market: str = "",
    universe: str = "",
) -> IdeaValidationResult:
    """
    Validate one ProposedIdea. `market`/`universe` are used only to build the
    feasibility spec; data-dir checks are skipped (no live data needed).
    """
    reasons: list[str] = []

    # --- non-empty hypothesis / signals --------------------------------------
    if not idea.hypothesis or not idea.hypothesis.strip():
        reasons.append("empty_hypothesis")
    if not idea.suggested_signals:
        reasons.append("empty_signals")

    # --- signal membership ----------------------------------------------------
    unknown = [s for s in idea.suggested_signals if s not in KNOWN_SIGNALS]
    if unknown:
        reasons.append(f"unknown_signal(s): {unknown}")

    # --- duplicate detection --------------------------------------------------
    norm = _normalise(idea.hypothesis) if idea.hypothesis else ""
    if norm:
        if norm in {_normalise(h) for h in existing_hypotheses}:
            reasons.append("duplicate_of_existing_experiment")
        if norm in {_normalise(f) for f in lesson_findings}:
            reasons.append("duplicate_of_lesson")
        if norm in {_normalise(h) for h in prior_idea_hypotheses}:
            reasons.append("duplicate_of_prior_idea")

    # --- feasibility via validate_spec() -------------------------------------
    # Only attempt if signals look structurally usable; validate_spec will also
    # re-check signal membership, but we surface its errors explicitly.
    spec = ExperimentSpec(
        hypothesis=idea.hypothesis or "",
        market=market or "unknown",
        universe=universe or "unknown",
        target=_DEFAULT_TARGET,
        features=list(idea.suggested_signals),
        model=_DEFAULT_MODEL,
        validation_method=_DEFAULT_VALIDATION_METHOD,
        success_criteria=_DEFAULT_SUCCESS_CRITERIA,
        expected_improvement="Positive Sharpe vs. random",
    )
    spec_result = validate_spec(spec, data_root=Path("."), skip_data_check=True)
    if not spec_result.valid:
        for err in spec_result.errors:
            reasons.append(f"spec_invalid: {err}")

    # De-duplicate reasons while preserving order.
    seen: set[str] = set()
    deduped = [r for r in reasons if not (r in seen or seen.add(r))]
    return IdeaValidationResult(ok=len(deduped) == 0, reasons=deduped)
