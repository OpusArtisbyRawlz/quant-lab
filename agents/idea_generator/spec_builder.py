"""
spec_builder.py — convert an approved idea row into an ExperimentSpec (M7).

Pure function, no I/O. Reads market/universe/hypothesis/suggested_signals from
the approved `pending_ideas` row (so the spec reflects exactly what was
approved) and fills target/model/validation_method from the same designer
defaults the M4 Experiment Designer uses, keeping idea-sourced experiments
consistent with hand-authored ones.

One idea -> one spec -> one experiment. No expansion, no combination.
"""

from __future__ import annotations

from typing import Any

from agents.protocol import ExperimentSpec, normalize_bar_type

# Mirror the Experiment Designer's defaults (agents/experiment_designer/designer.py).
_DEFAULT_MODEL = "quantile_ranking"
_DEFAULT_TARGET = "fwd_ret_5"
_DEFAULT_VALIDATION_METHOD = "walk_forward"
_DEFAULT_SUCCESS_CRITERIA: dict[str, Any] = {"sharpe": 0.5}


def idea_to_spec(
    idea_row: dict,
    *,
    success_criteria: dict[str, Any] | None = None,
    project: str = "idea_generator",
) -> ExperimentSpec:
    """
    Build an ExperimentSpec from an approved pending_ideas row.

    `idea_row` is a dict as returned by approval_queue.get_approved / list_approved
    (suggested_signals already deserialized to a list). Market and universe come
    from the idea itself — never from a global default.
    """
    signals = idea_row.get("suggested_signals") or []
    if isinstance(signals, str):  # defensive: not yet deserialized
        import json
        try:
            signals = json.loads(signals)
        except (json.JSONDecodeError, TypeError):
            signals = []

    return ExperimentSpec(
        hypothesis=idea_row.get("hypothesis", ""),
        market=idea_row.get("market", "") or "unknown",
        universe=idea_row.get("universe", "") or "unknown",
        target=_DEFAULT_TARGET,
        features=list(signals),
        model=_DEFAULT_MODEL,
        validation_method=_DEFAULT_VALIDATION_METHOD,
        success_criteria=dict(success_criteria or _DEFAULT_SUCCESS_CRITERIA),
        expected_improvement="Positive net Sharpe vs. random (LLM-proposed idea)",
        bar_type=normalize_bar_type(idea_row.get("bar_type")),
        project=project,
        notes=f"Auto-generated from approved idea {idea_row.get('idea_id', '?')} "
              f"(source_model={idea_row.get('source_model', '?')}).",
    )
