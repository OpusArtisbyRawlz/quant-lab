"""
Experiment ledger — reads and writes the experiments table.

The CSV at experiments/registry.csv remains the human-readable source of truth.
This store provides structured query access and is the write target for new agent cycles.
"""

from __future__ import annotations
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH

REGISTRY_CSV = Path(__file__).parent.parent.parent / "experiments" / "registry.csv"

_CSV_COLUMNS = [
    "experiment_id", "project", "date", "hypothesis", "target",
    "features", "model", "validation", "primary_metric", "result_summary",
    "conclusion", "status", "next_action", "artifact_path",
]


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def upsert_experiment(record: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Insert or replace an experiment row. Accepts any subset of columns."""
    record = _coerce(record)
    now = datetime.now(timezone.utc).isoformat()
    record.setdefault("created_at", now)
    record["updated_at"] = now

    columns = list(record.keys())
    placeholders = ", ".join("?" for _ in columns)
    col_str = ", ".join(columns)
    update_str = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "experiment_id")

    sql = f"""
        INSERT INTO experiments ({col_str}) VALUES ({placeholders})
        ON CONFLICT(experiment_id) DO UPDATE SET {update_str}, updated_at = excluded.updated_at
    """
    with get_connection(db_path) as conn:
        conn.execute(sql, list(record.values()))
        conn.commit()


def update_status(experiment_id: str, status: str, decision: str | None = None,
                  next_action: str | None = None, db_path: Path = DB_PATH) -> None:
    sets = ["status = ?", "updated_at = ?"]
    vals: list[Any] = [status, datetime.now(timezone.utc).isoformat()]
    if decision is not None:
        sets.append("decision = ?")
        vals.append(decision)
    if next_action is not None:
        sets.append("next_action = ?")
        vals.append(next_action)
    vals.append(experiment_id)
    with get_connection(db_path) as conn:
        conn.execute(f"UPDATE experiments SET {', '.join(sets)} WHERE experiment_id = ?", vals)
        conn.commit()


def update_metrics(experiment_id: str, metrics: dict[str, float],
                   result_summary: str = "", db_path: Path = DB_PATH) -> None:
    allowed = {"sharpe", "mdd", "cagr", "vol", "calmar"}
    sets = ["updated_at = ?"]
    vals: list[Any] = [datetime.now(timezone.utc).isoformat()]
    for k, v in metrics.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if result_summary:
        sets.append("result_summary = ?")
        vals.append(result_summary)
    vals.append(experiment_id)
    with get_connection(db_path) as conn:
        conn.execute(f"UPDATE experiments SET {', '.join(sets)} WHERE experiment_id = ?", vals)
        conn.commit()


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_experiment(experiment_id: str, db_path: Path = DB_PATH) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
        return dict(row) if row else None


def list_experiments(status: str | None = None, db_path: Path = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM experiments WHERE status = ? ORDER BY date DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM experiments ORDER BY date DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_best_experiments(metric: str = "sharpe", top_n: int = 5,
                         db_path: Path = DB_PATH) -> list[dict]:
    allowed = {"sharpe", "calmar", "cagr"}
    if metric not in allowed:
        raise ValueError(f"metric must be one of {allowed}")
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM experiments WHERE {metric} IS NOT NULL "
            f"ORDER BY {metric} DESC LIMIT ?", (top_n,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_rejected_experiments(db_path: Path = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE decision = 'reject' ORDER BY date DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def summary_stats(db_path: Path = DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        by_decision = conn.execute(
            "SELECT decision, COUNT(*) AS n FROM experiments GROUP BY decision"
        ).fetchall()
        avg_sharpe = conn.execute(
            "SELECT AVG(sharpe) FROM experiments WHERE sharpe IS NOT NULL"
        ).fetchone()[0]
        return {
            "total": total,
            "by_decision": {r["decision"]: r["n"] for r in by_decision},
            "avg_sharpe": round(avg_sharpe, 4) if avg_sharpe else None,
        }


# ---------------------------------------------------------------------------
# CSV sync — import registry.csv into DB (non-destructive, upsert)
# ---------------------------------------------------------------------------

def import_from_csv(csv_path: Path = REGISTRY_CSV, db_path: Path = DB_PATH) -> int:
    """Parse experiments/registry.csv and upsert all rows into the DB. Returns row count."""
    if not csv_path.exists():
        return 0
    imported = 0
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            exp_id = row.get("experiment_id", "").strip().strip('"')
            if not exp_id:
                continue
            record: dict[str, Any] = {
                "experiment_id": exp_id,
                "project": _clean(row.get("project")),
                "date": _clean(row.get("date")),
                "hypothesis": _clean(row.get("hypothesis")),
                "target": _clean(row.get("target")),
                "features": _clean(row.get("features")),
                "model": _clean(row.get("model")),
                "validation_method": _clean(row.get("validation")),
                "primary_metric": _clean(row.get("primary_metric")),
                "result_summary": _clean(row.get("result_summary")),
                "conclusion": _clean(row.get("conclusion")),
                "status": _clean(row.get("status")),
                "next_action": _clean(row.get("next_action")),
                "artifact_path": _clean(row.get("artifact_path")),
            }
            upsert_experiment(record, db_path)
            imported += 1
    return imported


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _clean(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip().strip('"')
    return s if s else None


def _coerce(record: dict[str, Any]) -> dict[str, Any]:
    """Serialize list/dict fields to JSON strings."""
    out = {}
    for k, v in record.items():
        if isinstance(v, (list, dict)):
            out[k] = json.dumps(v)
        else:
            out[k] = v
    return out
