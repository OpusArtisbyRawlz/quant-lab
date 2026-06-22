"""
context_store — reads and writes the Milestone 9 context-aware signal tables.

The atomic unit of signal knowledge is the *context cell*:

    (feature_name, market, universe, regime, bar_type)

No global aggregate is ever a stored primary. `signal_context_observation` is an
append-only fact table (one row per experiment x feature); every roll-up — per
context cell, per market, per universe, or global — is derived from it. The
`signal_context_performance` cache is a materialised 1:1 roll-up of the
observation groups at the full context-cell grain, kept solely for reporting
efficiency and rebuildable from observations at any time.

Regime is a deterministic, reproducible label computed from an experiment's own
stored volatility. The classifier `method` string is persisted alongside each
label so labels can be reproduced and re-labelled when the classifier evolves.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .db import get_connection, DB_PATH

# ---------------------------------------------------------------------------
# Context-dimension constants
# ---------------------------------------------------------------------------

UNKNOWN = "unknown"
REGIME_ALL = "all"            # sentinel used when no regime can be determined
DEFAULT_BAR_TYPE = "time"     # M9 default; volume/dollar/tick bars are future work
DEFAULT_ATTRIBUTION = "observational"

# The five dimensions of a context cell, in canonical order.
CONTEXT_DIMENSIONS = ("feature_name", "market", "universe", "regime", "bar_type")

# Default classifier version. A fixed-threshold scheme on annualised volatility:
# deterministic and reproducible per-experiment with no population reference, so
# it is stable as the experiment corpus grows. Bump the version (and re-label)
# to change semantics rather than mutating an existing method's thresholds.
DEFAULT_REGIME_METHOD = "vol_threshold_v1"

# Interior boundaries for vol_threshold_v1, on annualised volatility (a fraction).
_VOL_LOW_HI = 0.15
_VOL_HIGH_LO = 0.30


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

def classify_regime(vol: float | None,
                    method: str = DEFAULT_REGIME_METHOD) -> str:
    """Map an experiment's annualised volatility to a regime label.

    vol_threshold_v1: vol < 0.15 -> 'low_vol', vol >= 0.30 -> 'high_vol',
    otherwise 'mid_vol'. A missing/non-finite vol yields the 'all' sentinel so
    the experiment still contributes to regime-agnostic roll-ups without being
    mislabelled.
    """
    if method != DEFAULT_REGIME_METHOD:
        raise ValueError(f"unknown regime method: {method!r}")
    if vol is None:
        return REGIME_ALL
    try:
        v = float(vol)
    except (TypeError, ValueError):
        return REGIME_ALL
    if v != v:  # NaN
        return REGIME_ALL
    if v < _VOL_LOW_HI:
        return "low_vol"
    if v >= _VOL_HIGH_LO:
        return "high_vol"
    return "mid_vol"


def record_regime_label(experiment_id: str, regime: str,
                        method: str = DEFAULT_REGIME_METHOD,
                        db_path: Path = DB_PATH) -> None:
    """Persist (or refresh) the regime label for one experiment under `method`."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO regime_label (experiment_id, regime, method, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(experiment_id, method)
            DO UPDATE SET regime = excluded.regime, created_at = excluded.created_at
            """,
            (experiment_id, regime, method, now),
        )
        conn.commit()


def get_regime_label(experiment_id: str, method: str = DEFAULT_REGIME_METHOD,
                     db_path: Path = DB_PATH) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT regime FROM regime_label WHERE experiment_id = ? AND method = ?",
            (experiment_id, method),
        ).fetchone()
        return row["regime"] if row else None


# ---------------------------------------------------------------------------
# Observation writes (append-only provenance)
# ---------------------------------------------------------------------------

def add_context_observation(
    *,
    experiment_id: str,
    feature_name: str,
    market: str = UNKNOWN,
    universe: str = UNKNOWN,
    regime: str = REGIME_ALL,
    bar_type: str = DEFAULT_BAR_TYPE,
    attribution_method: str = DEFAULT_ATTRIBUTION,
    net_sharpe: float | None = None,
    net_calmar: float | None = None,
    kept: int | None = None,
    marginal_net_sharpe: float | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Record one (experiment x feature) observation in a given context.

    Idempotent on (experiment_id, feature_name, attribution_method): re-running
    the librarian over the same experiment recomputes identical values rather
    than appending duplicates, so the fact table stays effectively immutable.
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO signal_context_observation
                (experiment_id, feature_name, market, universe, regime, bar_type,
                 attribution_method, net_sharpe, net_calmar, kept,
                 marginal_net_sharpe, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(experiment_id, feature_name, attribution_method)
            DO UPDATE SET
                market = excluded.market,
                universe = excluded.universe,
                regime = excluded.regime,
                bar_type = excluded.bar_type,
                net_sharpe = excluded.net_sharpe,
                net_calmar = excluded.net_calmar,
                kept = excluded.kept,
                marginal_net_sharpe = excluded.marginal_net_sharpe
            """,
            (experiment_id, feature_name, market, universe, regime, bar_type,
             attribution_method, net_sharpe, net_calmar, kept,
             marginal_net_sharpe, now),
        )
        conn.commit()


def list_observations(feature_name: str | None = None,
                      experiment_id: str | None = None,
                      db_path: Path = DB_PATH) -> list[dict]:
    clauses, vals = [], []
    if feature_name is not None:
        clauses.append("feature_name = ?")
        vals.append(feature_name)
    if experiment_id is not None:
        clauses.append("experiment_id = ?")
        vals.append(experiment_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_context_observation {where} ORDER BY id", vals
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Aggregation engine (shared by cache rebuild and read-time roll-ups)
# ---------------------------------------------------------------------------

def _aggregate(conn, group_cols: Iterable[str], *,
               attribution_method: str = DEFAULT_ATTRIBUTION,
               where: str = "", params: tuple = ()) -> list[dict]:
    """Aggregate observations grouped by `group_cols`.

    The same function powers the full-grain cache rebuild and coarser read-time
    roll-ups (global / per-market / per-regime …) — the only difference is which
    columns appear in `group_cols`, which is why granular provenance is never
    lost: a coarse number is always an honest re-aggregation of the same facts.
    """
    group_cols = list(group_cols)
    select_cols = ", ".join(group_cols)
    select_prefix = f"{select_cols}," if group_cols else ""
    group_by = f"GROUP BY {select_cols}" if group_cols else ""

    clauses = ["attribution_method = ?"]
    all_params: list[Any] = [attribution_method]
    if where:
        clauses.append(where)
        all_params.extend(params)
    where_sql = "WHERE " + " AND ".join(clauses)

    # contribution_score uses marginal_net_sharpe for causal (ablation)
    # attribution and net_sharpe for observational attribution.
    contribution = (
        "AVG(marginal_net_sharpe)" if attribution_method == "ablation"
        else "AVG(net_sharpe)"
    )

    sql = f"""
        SELECT {select_prefix}
               COUNT(*)                    AS n_experiments,
               COUNT(net_sharpe)           AS n_with_net,
               COALESCE(SUM(kept), 0)      AS n_kept,
               AVG(net_sharpe)             AS avg_net_sharpe,
               AVG(net_calmar)             AS avg_net_calmar,
               AVG(CASE WHEN kept IS NOT NULL THEN CAST(kept AS REAL) END) AS keep_rate,
               {contribution}              AS contribution_score
        FROM signal_context_observation
        {where_sql}
        {group_by}
    """
    rows = conn.execute(sql, all_params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Cache rebuild
# ---------------------------------------------------------------------------

def rebuild_context_cache(db_path: Path = DB_PATH, *, min_n: int = 2) -> int:
    """Re-materialise signal_context_performance from observations.

    The cache is a 1:1 roll-up of observation groups at the full context-cell
    grain, for both observational and ablation attribution. Dropping and
    rebuilding it must reproduce identical numbers — it carries no information
    the observation table does not. `min_n` sets the evidence-sufficiency flag
    (`min_n_met`) used downstream to gate promotion decisions. Returns the
    number of cache rows written.
    """
    now = datetime.now(timezone.utc).isoformat()
    grain = list(CONTEXT_DIMENSIONS)
    written = 0
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM signal_context_performance")
        methods = [r["attribution_method"] for r in conn.execute(
            "SELECT DISTINCT attribution_method FROM signal_context_observation"
        ).fetchall()]
        for method in methods:
            for agg in _aggregate(conn, grain, attribution_method=method):
                conn.execute(
                    """
                    INSERT INTO signal_context_performance
                        (feature_name, market, universe, regime, bar_type,
                         attribution_method, n_experiments, n_with_net, n_kept,
                         avg_net_sharpe, avg_net_calmar, keep_rate,
                         contribution_score, min_n_met, last_rebuilt_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agg["feature_name"], agg["market"], agg["universe"],
                        agg["regime"], agg["bar_type"], method,
                        agg["n_experiments"], agg["n_with_net"], agg["n_kept"],
                        _round(agg["avg_net_sharpe"]), _round(agg["avg_net_calmar"]),
                        _round(agg["keep_rate"]), _round(agg["contribution_score"]),
                        1 if agg["n_experiments"] >= min_n else 0, now,
                    ),
                )
                written += 1
        conn.commit()
    return written


# ---------------------------------------------------------------------------
# Read API — context-filtered reads and roll-ups
# ---------------------------------------------------------------------------

def context_performance(
    *,
    feature_name: str | None = None,
    market: str | None = None,
    universe: str | None = None,
    regime: str | None = None,
    bar_type: str | None = None,
    attribution_method: str = DEFAULT_ATTRIBUTION,
    min_n: int | None = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Read context cells from the cache, filtered to any subset of dimensions.

    Passing no filters returns every context cell (the most granular view).
    Filtering by, e.g., market='India' answers "which signals work in India and
    in which regimes". This is the context-filtered read the IdeaGenerator and
    the reporting layer consume.
    """
    clauses = ["attribution_method = ?"]
    vals: list[Any] = [attribution_method]
    for col, val in (("feature_name", feature_name), ("market", market),
                     ("universe", universe), ("regime", regime),
                     ("bar_type", bar_type)):
        if val is not None:
            clauses.append(f"{col} = ?")
            vals.append(val)
    if min_n is not None:
        clauses.append("n_experiments >= ?")
        vals.append(min_n)
    where = " AND ".join(clauses)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM signal_context_performance
            WHERE {where}
            ORDER BY contribution_score IS NULL, contribution_score DESC,
                     n_experiments DESC
            """,
            vals,
        ).fetchall()
        return [dict(r) for r in rows]


def roll_up(
    dimensions: Iterable[str],
    *,
    attribution_method: str = DEFAULT_ATTRIBUTION,
    feature_name: str | None = None,
    market: str | None = None,
    universe: str | None = None,
    regime: str | None = None,
    bar_type: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Aggregate observations to a coarser level than the stored grain.

    `dimensions` is any subset of CONTEXT_DIMENSIONS to group by. Examples:
      roll_up(["feature_name"])                 -> global per-signal numbers
      roll_up(["feature_name", "market"])       -> per-signal-per-market numbers
      roll_up(["market"])                        -> per-market numbers
    Optional equality filters restrict the underlying facts before grouping.
    Every result is an honest re-aggregation of the same observation rows, so a
    global number can never disagree with the cell-level provenance behind it.
    """
    dims = [d for d in dimensions if d in CONTEXT_DIMENSIONS]
    clauses, params = [], []
    for col, val in (("feature_name", feature_name), ("market", market),
                     ("universe", universe), ("regime", regime),
                     ("bar_type", bar_type)):
        if val is not None:
            clauses.append(f"{col} = ?")
            params.append(val)
    where = " AND ".join(clauses)
    with get_connection(db_path) as conn:
        rows = _aggregate(conn, dims, attribution_method=attribution_method,
                          where=where, params=tuple(params))
    for r in rows:
        for k in ("avg_net_sharpe", "avg_net_calmar", "keep_rate",
                  "contribution_score"):
            r[k] = _round(r[k])
    rows.sort(key=lambda r: (r.get("contribution_score") is None,
                             -(r.get("contribution_score") or 0.0),
                             -r["n_experiments"]))
    return rows


def distinct_context_count(feature_name: str, *,
                           attribution_method: str = DEFAULT_ATTRIBUTION,
                           min_n: int = 1, threshold: float | None = None,
                           db_path: Path = DB_PATH) -> int:
    """Count distinct context cells in which a signal has been observed.

    When `threshold` is given, only counts cells whose contribution_score clears
    it (and which meet `min_n`). Used to gauge how broadly a signal generalises.
    """
    cells = context_performance(feature_name=feature_name,
                                attribution_method=attribution_method,
                                db_path=db_path)
    count = 0
    for c in cells:
        if c["n_experiments"] < min_n:
            continue
        if threshold is not None:
            score = c["contribution_score"]
            if score is None or score < threshold:
                continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _round(x: Any, ndigits: int = 4) -> float | None:
    return round(x, ndigits) if x is not None else None
