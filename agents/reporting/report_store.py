"""
report_store — the ONLY database-touching module in the reporting package.

Every function here issues read-only SELECT/aggregation queries against the
shared SQLite store and returns plain typed dataclasses. No INSERT/UPDATE/
DELETE/ALTER is ever issued. Callers in summaries.py / report.py operate purely
on the returned dataclasses and never open their own connection.

Design notes
------------
* "Experiments that came from an LLM idea" are exactly the rows where
  source_idea_id IS NOT NULL. source_model is therefore only meaningful on those
  rows, so every source_model aggregate filters on source_idea_id IS NOT NULL.
* Net metrics (net_sharpe, net_calmar, ...) are NULL for pre-M5 experiments, so
  every average over a net metric filters out NULLs and reports the contributing
  count (n_with_net) alongside the figure.
* robustness_flags and validation_reasons are JSON-array TEXT columns. We unnest
  them with SQLite's JSON1 json_each() when available, and fall back to a Python
  Counter over json.loads(...) when the build lacks JSON1.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.storage.db import get_connection, DB_PATH


# ---------------------------------------------------------------------------
# Dataclasses (the typed reporting vocabulary)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceModelStat:
    """Performance roll-up for one idea-proposing model."""
    source_model: str
    n_experiments: int          # experiments stamped with this source_model
    n_with_net: int             # of those, how many have a non-NULL net_sharpe
    avg_net_sharpe: float | None
    avg_net_calmar: float | None
    keep_rate: float | None     # fraction with decision == 'keep' (NULL if n==0)


@dataclass(frozen=True)
class GroupStat:
    """Performance roll-up for one market or universe."""
    key: str
    n_experiments: int
    n_with_net: int
    avg_net_sharpe: float | None
    avg_net_calmar: float | None
    keep_rate: float | None


@dataclass(frozen=True)
class ComboStat:
    """Performance roll-up for one market+universe+source_model combination."""
    market: str
    universe: str
    source_model: str
    n_experiments: int
    n_with_net: int
    avg_net_sharpe: float | None
    avg_net_calmar: float | None
    keep_rate: float | None


@dataclass(frozen=True)
class FunnelStat:
    """Idea lifecycle funnel from proposal to executed experiment."""
    total: int
    pending: int
    approved: int
    executing: int
    executed: int
    rejected: int
    approval_rate: float | None     # (approved+executing+executed) / total
    rejection_rate: float | None    # rejected / total
    execution_rate: float | None    # executed / total


@dataclass(frozen=True)
class CountStat:
    """A label and its count, for ranked frequency tables."""
    label: str
    count: int


@dataclass(frozen=True)
class DecisionStat:
    """Critic decision breakdown over idea-originated experiments."""
    total: int
    keep: int
    reject: int
    retest: int
    keep_rate: float | None
    survival_rate: float | None     # (keep+retest) / total — survived the Critic


@dataclass(frozen=True)
class BucketStat:
    """One bucket of the net-Sharpe histogram."""
    lower: float | None             # None => open-ended (-inf) lowest bucket
    upper: float | None             # None => open-ended (+inf) highest bucket
    count: int


@dataclass(frozen=True)
class OverviewStat:
    """Top-level counts for the report header."""
    total_experiments: int
    idea_experiments: int           # source_idea_id IS NOT NULL
    total_ideas: int
    total_lessons: int
    avg_net_sharpe: float | None
    n_with_net: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _round(x: Any, ndigits: int = 4) -> float | None:
    return round(x, ndigits) if x is not None else None


def _rate(num: int, denom: int) -> float | None:
    return round(num / denom, 4) if denom else None


def _json1_available(conn) -> bool:
    try:
        conn.execute("SELECT json_each.value FROM json_each('[1]')").fetchone()
        return True
    except Exception:
        return False


def _count_json_array_column(conn, table: str, column: str,
                             where: str = "") -> list[CountStat]:
    """Unnest a JSON-array TEXT column and count element frequencies.

    Uses JSON1 json_each when available, else a Python Counter fallback. Both
    paths ignore NULL/empty cells and malformed JSON.
    """
    clause = f"WHERE {where}" if where else ""
    if _json1_available(conn):
        rows = conn.execute(
            f"""
            SELECT je.value AS label, COUNT(*) AS n
            FROM {table} t, json_each(t.{column}) je
            {clause}
            GROUP BY je.value
            ORDER BY n DESC, label ASC
            """
        ).fetchall()
        return [CountStat(label=str(r["label"]), count=r["n"]) for r in rows]

    # Fallback: pull raw cells and count in Python.
    rows = conn.execute(f"SELECT {column} AS raw FROM {table} {clause}").fetchall()
    counter: Counter[str] = Counter()
    for r in rows:
        raw = r["raw"]
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            for el in parsed:
                counter[str(el)] += 1
    return [CountStat(label=k, count=v)
            for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]


# Shared SELECT fragment for net-metric group aggregates.
_GROUP_SELECT = """
    COUNT(*)                                              AS n_experiments,
    COUNT(net_sharpe)                                     AS n_with_net,
    AVG(net_sharpe)                                       AS avg_net_sharpe,
    AVG(net_calmar)                                       AS avg_net_calmar,
    AVG(CASE WHEN decision = 'keep' THEN 1.0 ELSE 0.0 END) AS keep_rate
"""


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------

def source_model_stats(db_path: Path = DB_PATH) -> list[SourceModelStat]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT source_model AS key, {_GROUP_SELECT}
            FROM experiments
            WHERE source_idea_id IS NOT NULL AND source_model IS NOT NULL
            GROUP BY source_model
            ORDER BY avg_net_sharpe IS NULL, avg_net_sharpe DESC, n_experiments DESC
            """
        ).fetchall()
    return [
        SourceModelStat(
            source_model=r["key"],
            n_experiments=r["n_experiments"],
            n_with_net=r["n_with_net"],
            avg_net_sharpe=_round(r["avg_net_sharpe"]),
            avg_net_calmar=_round(r["avg_net_calmar"]),
            keep_rate=_round(r["keep_rate"]),
        )
        for r in rows
    ]


def _group_stats(column: str, db_path: Path) -> list[GroupStat]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE({column}, 'unknown') AS key, {_GROUP_SELECT}
            FROM experiments
            GROUP BY COALESCE({column}, 'unknown')
            ORDER BY avg_net_sharpe IS NULL, avg_net_sharpe DESC, n_experiments DESC
            """
        ).fetchall()
    return [
        GroupStat(
            key=r["key"],
            n_experiments=r["n_experiments"],
            n_with_net=r["n_with_net"],
            avg_net_sharpe=_round(r["avg_net_sharpe"]),
            avg_net_calmar=_round(r["avg_net_calmar"]),
            keep_rate=_round(r["keep_rate"]),
        )
        for r in rows
    ]


def market_stats(db_path: Path = DB_PATH) -> list[GroupStat]:
    return _group_stats("market", db_path)


def universe_stats(db_path: Path = DB_PATH) -> list[GroupStat]:
    return _group_stats("universe", db_path)


def combo_stats(db_path: Path = DB_PATH, min_n: int = 1) -> list[ComboStat]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE(market, 'unknown')       AS market,
                   COALESCE(universe, 'unknown')     AS universe,
                   COALESCE(source_model, 'unknown') AS source_model,
                   {_GROUP_SELECT}
            FROM experiments
            WHERE source_idea_id IS NOT NULL
            GROUP BY COALESCE(market, 'unknown'),
                     COALESCE(universe, 'unknown'),
                     COALESCE(source_model, 'unknown')
            HAVING COUNT(*) >= ?
            ORDER BY avg_net_sharpe IS NULL, avg_net_sharpe DESC, n_experiments DESC
            """,
            (min_n,),
        ).fetchall()
    return [
        ComboStat(
            market=r["market"],
            universe=r["universe"],
            source_model=r["source_model"],
            n_experiments=r["n_experiments"],
            n_with_net=r["n_with_net"],
            avg_net_sharpe=_round(r["avg_net_sharpe"]),
            avg_net_calmar=_round(r["avg_net_calmar"]),
            keep_rate=_round(r["keep_rate"]),
        )
        for r in rows
    ]


def idea_funnel(db_path: Path = DB_PATH) -> FunnelStat:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM pending_ideas GROUP BY status"
        ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    pending = counts.get("pending", 0)
    approved = counts.get("approved", 0)
    executing = counts.get("executing", 0)
    executed = counts.get("executed", 0)
    rejected = counts.get("rejected", 0)
    total = pending + approved + executing + executed + rejected
    return FunnelStat(
        total=total,
        pending=pending,
        approved=approved,
        executing=executing,
        executed=executed,
        rejected=rejected,
        approval_rate=_rate(approved + executing + executed, total),
        rejection_rate=_rate(rejected, total),
        execution_rate=_rate(executed, total),
    )


def rejection_reasons(db_path: Path = DB_PATH) -> list[CountStat]:
    with get_connection(db_path) as conn:
        return _count_json_array_column(
            conn, "pending_ideas", "validation_reasons",
            where="validation_ok = 0",
        )


def critic_decisions(db_path: Path = DB_PATH) -> DecisionStat:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT decision, COUNT(*) AS n
            FROM experiments
            WHERE source_idea_id IS NOT NULL AND decision IS NOT NULL
            GROUP BY decision
            """
        ).fetchall()
    counts = {r["decision"]: r["n"] for r in rows}
    keep = counts.get("keep", 0)
    reject = counts.get("reject", 0)
    retest = counts.get("retest", 0)
    total = keep + reject + retest
    return DecisionStat(
        total=total,
        keep=keep,
        reject=reject,
        retest=retest,
        keep_rate=_rate(keep, total),
        survival_rate=_rate(keep + retest, total),
    )


def lesson_categories(db_path: Path = DB_PATH) -> list[CountStat]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(category, 'other') AS label, COUNT(*) AS n
            FROM lessons_learned
            GROUP BY COALESCE(category, 'other')
            ORDER BY n DESC, label ASC
            """
        ).fetchall()
    return [CountStat(label=r["label"], count=r["n"]) for r in rows]


def robustness_flag_counts(db_path: Path = DB_PATH) -> list[CountStat]:
    with get_connection(db_path) as conn:
        return _count_json_array_column(conn, "experiments", "robustness_flags")


def net_sharpe_buckets(db_path: Path = DB_PATH,
                       edges: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5, 2.0)
                       ) -> list[BucketStat]:
    """Histogram of net_sharpe over experiments with a non-NULL net_sharpe.

    `edges` are the interior boundaries; the result has len(edges)+1 buckets,
    the first open below edges[0] and the last open at/above edges[-1].
    Bucket membership is [lower, upper).
    """
    edges = tuple(sorted(edges))
    with get_connection(db_path) as conn:
        vals = [r[0] for r in conn.execute(
            "SELECT net_sharpe FROM experiments WHERE net_sharpe IS NOT NULL"
        ).fetchall()]

    bounds: list[tuple[float | None, float | None]] = []
    bounds.append((None, edges[0]))
    for i in range(len(edges) - 1):
        bounds.append((edges[i], edges[i + 1]))
    bounds.append((edges[-1], None))

    counts = [0] * len(bounds)
    for v in vals:
        placed = False
        for i, (lo, hi) in enumerate(bounds):
            lo_ok = lo is None or v >= lo
            hi_ok = hi is None or v < hi
            if lo_ok and hi_ok:
                counts[i] += 1
                placed = True
                break
        if not placed:  # pragma: no cover - bounds are exhaustive
            counts[-1] += 1
    return [BucketStat(lower=lo, upper=hi, count=c)
            for (lo, hi), c in zip(bounds, counts)]


def overview(db_path: Path = DB_PATH) -> OverviewStat:
    with get_connection(db_path) as conn:
        total_exp = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        idea_exp = conn.execute(
            "SELECT COUNT(*) FROM experiments WHERE source_idea_id IS NOT NULL"
        ).fetchone()[0]
        total_ideas = conn.execute("SELECT COUNT(*) FROM pending_ideas").fetchone()[0]
        total_lessons = conn.execute("SELECT COUNT(*) FROM lessons_learned").fetchone()[0]
        row = conn.execute(
            "SELECT AVG(net_sharpe) AS a, COUNT(net_sharpe) AS n FROM experiments"
        ).fetchone()
    return OverviewStat(
        total_experiments=total_exp,
        idea_experiments=idea_exp,
        total_ideas=total_ideas,
        total_lessons=total_lessons,
        avg_net_sharpe=_round(row["a"]),
        n_with_net=row["n"],
    )
