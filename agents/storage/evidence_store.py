"""
evidence_store — reads and writes the Milestone 11 PR-1 ``evidence_event`` table.

``evidence_event`` is the minimum durable evidence layer of the approved M11
design: one immutable, fully-provenanced row per (experiment x evidence source),
captured from a *finished* experiment. It is **append-only truth**. This module
is pure storage — it records and returns evidence and makes **no** promotion,
retirement, confidence, or deployment decision. Later M11 components (posterior
updating, promotion/retirement engines) read through the functions here.

Idempotency: the natural key is ``(experiment_id, evidence_source)``. Recording
the same finished experiment twice under the same source is a no-op
(``ON CONFLICT DO NOTHING``); distinct evidence sources for one experiment remain
separately captured, so a single strategy can accumulate in-sample, validation,
walk-forward, holdout, and live-paper evidence side by side.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

# The recognised evidence-source classifications. Every row carries exactly one.
SOURCE_IN_SAMPLE = "in_sample"
SOURCE_VALIDATION = "validation"
SOURCE_EMBARGO = "embargo"
SOURCE_WALK_FORWARD = "walk_forward"
SOURCE_HOLDOUT = "holdout"
SOURCE_LIVE_PAPER = "live_paper"

EVIDENCE_SOURCES = frozenset({
    SOURCE_IN_SAMPLE, SOURCE_VALIDATION, SOURCE_EMBARGO,
    SOURCE_WALK_FORWARD, SOURCE_HOLDOUT, SOURCE_LIVE_PAPER,
})

# JSON-typed columns, decoded on read.
_JSON_COLUMNS = ("feature_names", "metrics", "robustness_flags",
                 "capacity_metrics", "provenance")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True)


def _loads(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _row(r) -> dict[str, Any]:
    d = dict(r)
    for col in _JSON_COLUMNS:
        if col in d:
            d[col] = _loads(d.get(col))
    return d


# ---------------------------------------------------------------------------
# Write (append-only, idempotent)
# ---------------------------------------------------------------------------

def record_evidence(
    experiment_id: str,
    *,
    evidence_source: str = SOURCE_IN_SAMPLE,
    hypothesis_id: str | None = None,
    campaign_id: str | None = None,
    source_idea_id: str | None = None,
    source_model: str | None = None,
    market: str | None = None,
    universe: str | None = None,
    regime: str | None = None,
    bar_type: str = "time",
    feature_names: Any = None,
    dataset_id: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    methodology_version: str | None = None,
    stat_method_version: str | None = None,
    metrics: Any = None,
    robustness_flags: Any = None,
    capacity_metrics: Any = None,
    critic_decision: str | None = None,
    provenance: Any = None,
    db_path: Path = DB_PATH,
) -> int | None:
    """Append one immutable evidence event; idempotent on
    ``(experiment_id, evidence_source)``.

    Returns the new row id, or ``None`` if an event for this
    ``(experiment_id, evidence_source)`` already exists (no duplicate written).
    Pure storage: records provenance and metrics only, decides nothing.
    """
    if evidence_source not in EVIDENCE_SOURCES:
        raise ValueError(f"unknown evidence_source: {evidence_source!r}")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO evidence_event
                (experiment_id, hypothesis_id, campaign_id, source_idea_id,
                 source_model, market, universe, regime, bar_type,
                 feature_names, dataset_id, date_start, date_end,
                 evidence_source, methodology_version, stat_method_version,
                 metrics, robustness_flags, capacity_metrics, critic_decision,
                 provenance, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (experiment_id, evidence_source) DO NOTHING
            """,
            (experiment_id, hypothesis_id, campaign_id, source_idea_id,
             source_model, market, universe, regime, bar_type,
             _dumps(feature_names), dataset_id, date_start, date_end,
             evidence_source, methodology_version, stat_method_version,
             _dumps(metrics), _dumps(robustness_flags), _dumps(capacity_metrics),
             critic_decision, _dumps(provenance), _utcnow()),
        )
        conn.commit()
        # rowcount == 0 means the ON CONFLICT fired (duplicate) → no insert.
        if cur.rowcount == 0:
            return None
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Reads (pure functions of the stored log — for later M11 components)
# ---------------------------------------------------------------------------

def get_evidence(evidence_id: int, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM evidence_event WHERE id = ?", (evidence_id,)
        ).fetchone()
    return _row(row) if row else None


def list_evidence(
    *,
    experiment_id: str | None = None,
    hypothesis_id: str | None = None,
    campaign_id: str | None = None,
    evidence_source: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Return evidence events oldest-first (by id), optionally filtered."""
    clauses, vals = [], []
    for col, val in (("experiment_id", experiment_id),
                     ("hypothesis_id", hypothesis_id),
                     ("campaign_id", campaign_id),
                     ("evidence_source", evidence_source)):
        if val is not None:
            clauses.append(f"{col} = ?")
            vals.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM evidence_event {where} ORDER BY id", vals
        ).fetchall()
    return [_row(r) for r in rows]


def evidence_for_experiment(
    experiment_id: str, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    """All evidence events for one experiment (one per evidence source)."""
    return list_evidence(experiment_id=experiment_id, db_path=db_path)


def evidence_sources_for(
    experiment_id: str, db_path: Path = DB_PATH
) -> set[str]:
    """The set of evidence sources already captured for an experiment."""
    return {e["evidence_source"]
            for e in evidence_for_experiment(experiment_id, db_path=db_path)}


def has_evidence(
    experiment_id: str,
    evidence_source: str = SOURCE_IN_SAMPLE,
    db_path: Path = DB_PATH,
) -> bool:
    """Whether an event already exists for ``(experiment_id, evidence_source)``."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM evidence_event "
            "WHERE experiment_id = ? AND evidence_source = ? LIMIT 1",
            (experiment_id, evidence_source),
        ).fetchone()
    return row is not None


def distinct_experiment_ids(db_path: Path = DB_PATH) -> list[str]:
    """Every experiment_id that appears in the evidence log (reconciliation)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT experiment_id FROM evidence_event ORDER BY experiment_id"
        ).fetchall()
    return [r["experiment_id"] for r in rows]


def distinct_hypothesis_ids(db_path: Path = DB_PATH) -> list[str]:
    """Every non-null hypothesis_id present in the evidence log (for projection)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT hypothesis_id FROM evidence_event "
            "WHERE hypothesis_id IS NOT NULL ORDER BY hypothesis_id"
        ).fetchall()
    return [r["hypothesis_id"] for r in rows]


def count(db_path: Path = DB_PATH) -> int:
    """Total number of evidence events stored."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM evidence_event").fetchone()
    return int(row["n"]) if row else 0
