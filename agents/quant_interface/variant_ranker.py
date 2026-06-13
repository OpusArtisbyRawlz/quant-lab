"""
variant_ranker.py — Neutral ranking framework for strategy variants.

Design principles:
- Ingestion stores every variant without preference. This module is the
  only place where "better" is defined, and that definition is always
  caller-supplied.
- Ranking criteria are explicit, not implicit. Nothing defaults to Sharpe.
- Constraints filter the candidate set before ranking, not after.
- All functions accept the dict format returned by get_variants_for_experiment()
  so callers never need to re-query the database.

Usage
-----
    from agents.quant_interface.variant_ranker import rank_variants, top_variant

    variants = get_variants_for_experiment("exp_004_project04_final", db_path=db)

    # Rank by Sharpe, no constraints
    ranked = rank_variants(variants, by="sharpe")

    # Top Calmar with drawdown floor
    best = top_variant(variants, by="calmar", constraints={"max_mdd": -0.60})

    # All variants with Sharpe >= 1.4, sorted by lowest drawdown
    filtered = rank_variants(
        variants,
        by="mdd",
        ascending=True,          # lowest MDD first (least negative)
        constraints={"min_sharpe": 1.4},
    )
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported ranking metrics and their sort direction defaults
# ---------------------------------------------------------------------------

#: Metrics the ranker understands, mapped to default ascending flag.
#: False = higher is better → rank descending (largest value first)
#: True  = lower is better → rank ascending (smallest value first)
#:
#: MDD is negative, so "lowest drawdown" means least-negative = closest to 0.
#: Descending (False) puts -0.625 before -0.690 — i.e. smallest loss first.
#: Vol default is ascending (True): tightest vol is preferred by default.
_METRIC_DEFAULTS: dict[str, bool] = {
    "sharpe":        False,  # higher Sharpe is better
    "calmar":        False,  # higher Calmar is better
    "cagr":          False,  # higher CAGR is better
    "vol":           True,   # lower vol is tighter; caller overrides if needed
    "avg_exposure":  False,  # higher exposure = more invested (context-dependent)
    "mdd":           False,  # least-negative first: -0.625 before -0.690
}

# ---------------------------------------------------------------------------
# Constraint keys and the column + comparison they map to
# ---------------------------------------------------------------------------

#: Each constraint key maps to (column_name, operator).
#: Operator is "gte" (>=) or "lte" (<=).
_CONSTRAINT_MAP: dict[str, tuple[str, str]] = {
    "min_sharpe":       ("sharpe",       "gte"),
    "max_sharpe":       ("sharpe",       "lte"),
    "min_calmar":       ("calmar",       "gte"),
    "max_calmar":       ("calmar",       "lte"),
    "min_cagr":         ("cagr",         "gte"),
    "max_cagr":         ("cagr",         "lte"),
    "max_mdd":          ("mdd",          "gte"),   # MDD is negative: max_mdd=-0.5 means mdd >= -0.5
    "min_mdd":          ("mdd",          "lte"),   # floor on how negative MDD can be
    "max_vol":          ("vol",          "lte"),
    "min_vol":          ("vol",          "gte"),
    "min_avg_exposure": ("avg_exposure", "gte"),
    "max_avg_exposure": ("avg_exposure", "lte"),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rank_variants(
    variants: list[dict[str, Any]],
    by: str,
    constraints: dict[str, float] | None = None,
    ascending: bool | None = None,
) -> list[dict[str, Any]]:
    """
    Filter and rank strategy variants.

    Parameters
    ----------
    variants : list[dict]
        Rows from get_variants_for_experiment() or get_unpromoted_variants().
    by : str
        Column to rank by. One of: sharpe, calmar, cagr, vol, mdd, avg_exposure.
    constraints : dict, optional
        Key-value pairs that filter candidates before ranking.
        Supported keys: min_sharpe, max_mdd, min_calmar, max_vol, min_cagr,
        max_cagr, min_vol, max_sharpe, min_mdd, min_avg_exposure, max_avg_exposure.
        Example: {"min_sharpe": 1.2, "max_mdd": -0.55}
    ascending : bool, optional
        Override the default sort direction for the chosen metric.
        If None, uses the metric's natural default (see _METRIC_DEFAULTS).

    Returns
    -------
    list[dict]
        Filtered and sorted variants. Variants where `by` is NULL are
        always placed at the end regardless of direction.
    """
    if by not in _METRIC_DEFAULTS:
        raise ValueError(
            f"Unknown ranking metric: {by!r}. "
            f"Supported: {sorted(_METRIC_DEFAULTS)}"
        )

    candidates = _apply_constraints(variants, constraints or {})

    sort_ascending = ascending if ascending is not None else _METRIC_DEFAULTS[by]

    # Separate rows with and without the ranking metric populated
    with_value = [v for v in candidates if v.get(by) is not None]
    without_value = [v for v in candidates if v.get(by) is None]

    with_value.sort(key=lambda v: v[by], reverse=not sort_ascending)

    ranked = with_value + without_value
    log.debug(
        "rank_variants by=%s ascending=%s constraints=%s → %d/%d candidates",
        by, sort_ascending, constraints, len(ranked), len(variants),
    )
    return ranked


def top_variant(
    variants: list[dict[str, Any]],
    by: str,
    constraints: dict[str, float] | None = None,
    ascending: bool | None = None,
) -> dict[str, Any] | None:
    """
    Return the single highest-ranked variant, or None if no candidates pass
    the constraints or the variants list is empty.

    Parameters
    ----------
    variants, by, constraints, ascending
        Same as rank_variants().

    Returns
    -------
    dict or None
    """
    ranked = rank_variants(variants, by=by, constraints=constraints, ascending=ascending)
    # ranked may start with NULL-metric rows if every candidate has NULL — guard
    for v in ranked:
        if v.get(by) is not None:
            return v
    return None


def summarise(
    variants: list[dict[str, Any]],
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """
    Return summary statistics (min / max / mean) for the requested metrics
    across all non-NULL variant values.

    Parameters
    ----------
    variants : list[dict]
        Any collection of variant dicts.
    metrics : list[str], optional
        Columns to summarise. Defaults to all supported ranking metrics.

    Returns
    -------
    dict
        ``{metric: {"min": …, "max": …, "mean": …, "count": …}}``
        Missing metrics (all NULL) produce ``None`` for each stat.
    """
    cols = metrics or list(_METRIC_DEFAULTS)
    result: dict[str, Any] = {}
    for col in cols:
        values = [v[col] for v in variants if v.get(col) is not None]
        if values:
            result[col] = {
                "min":   min(values),
                "max":   max(values),
                "mean":  sum(values) / len(values),
                "count": len(values),
            }
        else:
            result[col] = None
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_constraints(
    variants: list[dict[str, Any]],
    constraints: dict[str, float],
) -> list[dict[str, Any]]:
    """Return only the variants that satisfy every supplied constraint."""
    if not constraints:
        return list(variants)

    unknown = set(constraints) - set(_CONSTRAINT_MAP)
    if unknown:
        raise ValueError(
            f"Unknown constraint key(s): {sorted(unknown)}. "
            f"Supported: {sorted(_CONSTRAINT_MAP)}"
        )

    filtered = []
    for v in variants:
        passes = True
        for constraint_key, threshold in constraints.items():
            col, op = _CONSTRAINT_MAP[constraint_key]
            val = v.get(col)
            if val is None:
                passes = False  # NULL values never satisfy a constraint
                break
            if op == "gte" and val < threshold:
                passes = False
                break
            if op == "lte" and val > threshold:
                passes = False
                break
        if passes:
            filtered.append(v)

    return filtered
