"""
research_memory_query — pure read-models over the M11 projections (PR-11, M11-7).

Answers standing research questions and renders read-only Reporter boards *purely
from the stored projections* — it re-runs nothing and recomputes no statistic. It
is the read side of M11's institutional memory: confidence/stage board, retirement
log, generalisation board, failure/overfit summaries, and the decision-record
explanations.

Every function is a pure reader over the stores of prior PRs; determinism and
append-only guarantees are inherited from those projections. This is a module of
read functions, not an agent.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import (
    promotion_store, retirement_store, failure_store, generalisation_store,
    decision_record_store,
)
from .failure import REASON_PARAMETER_FRAGILITY, REASON_COST_FRAGILITY


# --- boards ----------------------------------------------------------------

def stage_board(*, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Confidence/stage board: every hypothesis with its recommended stage,
    confidence (π_h) and axis summary (from ``promotion_recommendation``)."""
    return [
        {
            "hypothesis_id": r["hypothesis_id"],
            "stage": r["recommended_stage"],
            "tier": r["promotion_tier"],
            "confidence": r["confidence_score"],
            "g_count": r["g_count"],
            "v_net_sharpe": r["v_net_sharpe"],
        }
        for r in promotion_store.list_recommendations(db_path=db_path)
    ]


def retirement_log(*, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Retirement log: the retired hypotheses with state + reason."""
    return [
        {"hypothesis_id": r["hypothesis_id"], "state": r["state"],
         "reason": r["reason"]}
        for r in retirement_store.list_retirements(retired=True, db_path=db_path)
    ]


def generalisation_board(hypothesis_id: str, *,
                         db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Per-dimension generalisation survival for one hypothesis."""
    return generalisation_store.list_matrix(hypothesis_id, db_path=db_path)


# --- standing questions ----------------------------------------------------

def surviving_hypotheses(*, min_g_count: int = 2,
                         db_path: Path = DB_PATH) -> list[str]:
    """"What survives?" — hypotheses generalising across ≥ ``min_g_count`` cells."""
    seen: dict[str, int] = {}
    for hid in generalisation_store.distinct_hypotheses(db_path=db_path):
        rows = generalisation_store.list_matrix(hid, db_path=db_path)
        if rows and rows[0]["g_count"] >= min_g_count:
            seen[hid] = rows[0]["g_count"]
    return sorted(seen)


def market_transfer(hypothesis_id: str, *, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    """"Which markets transfer?" — the market-dimension coverage for a hypothesis."""
    m = generalisation_store.get_dimension(hypothesis_id, "market", db_path=db_path)
    if m is None:
        return None
    return {"hypothesis_id": hypothesis_id, "markets_passing": m["passing"],
            "markets_available": m["available"], "coverage": m["coverage"]}


def overfit_experiments(*, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """"What overfits?" — experiments rejected for parameter/cost fragility."""
    out: list[dict[str, Any]] = []
    for reason in (REASON_PARAMETER_FRAGILITY, REASON_COST_FRAGILITY):
        for f in failure_store.list_failures(reason_code=reason, db_path=db_path):
            out.append({"experiment_id": f["experiment_id"], "reason_code": reason})
    return sorted(out, key=lambda d: d["experiment_id"])


def failure_summary(*, db_path: Path = DB_PATH) -> dict[str, int]:
    """Counts of failures by reason code."""
    counts = Counter(f["reason_code"] for f in failure_store.list_failures(db_path=db_path))
    return dict(sorted(counts.items()))


# --- explanations ----------------------------------------------------------

def explanations_for(subject_id: str, *, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Every decision record about one subject (hypothesis or experiment)."""
    return decision_record_store.list_records(subject_id=subject_id, db_path=db_path)
