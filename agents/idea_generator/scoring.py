"""
scoring.py — advisory-only idea quality heuristics.

novelty_score, feasibility_score, signal_diversity_score are INFORMATIONAL.
They are never used to gate validation, approval, or execution — they exist so
idea quality can be analysed later. The exact logic is expected to change as
prompts/models/ranking evolve, which is why these live in JSON metadata rather
than dedicated schema columns.
"""

from __future__ import annotations

_SCORE_KEYS = ("novelty_score", "feasibility_score", "signal_diversity_score")


def _clamp(x: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def normalise_scores(supplied: dict) -> dict[str, float]:
    """Coerce a model-supplied score dict to the three known keys in [0, 1]."""
    return {k: _clamp(supplied.get(k, 0.0)) for k in _SCORE_KEYS}


def compute_scores(hypothesis: str, signals: tuple[str, ...]) -> dict[str, float]:
    """
    Cheap deterministic fallback when the model supplies no scores.

    Purely heuristic placeholders — not a quality judgement, just a stable
    default so the metadata shape is always populated.
    """
    n = len(signals)
    diversity = _clamp(len(set(signals)) / n) if n else 0.0
    feasibility = 1.0 if 0 < n <= 4 else 0.5
    novelty = _clamp(min(len(hypothesis), 120) / 120.0)
    return {
        "novelty_score": novelty,
        "feasibility_score": feasibility,
        "signal_diversity_score": diversity,
    }
