"""
Lessons learned — reads and writes the lessons_learned table.

Each lesson is a distilled insight extracted after one experiment cycle.
The Idea Generator reads these in Phase 2 to avoid repeating mistakes
and to prioritise promising directions.
"""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def add_lesson(
    experiment_id: str,
    finding: str,
    implication: str,
    category: str = "other",
    confidence: str = "medium",
    cycle_id: str | None = None,
    db_path: Path = DB_PATH,
) -> int:
    """Insert a new lesson. Returns the new row id."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO lessons_learned
                (experiment_id, cycle_id, category, finding, implication, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                cycle_id,
                category,
                finding,
                implication,
                confidence,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def bulk_add_lessons(lessons: list[dict[str, Any]], db_path: Path = DB_PATH) -> int:
    """Insert multiple lessons in one transaction. Returns count inserted."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            l["experiment_id"],
            l.get("cycle_id"),
            l.get("category", "other"),
            l["finding"],
            l.get("implication", ""),
            l.get("confidence", "medium"),
            now,
        )
        for l in lessons
    ]
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO lessons_learned
                (experiment_id, cycle_id, category, finding, implication, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_lessons_for_experiment(experiment_id: str,
                                db_path: Path = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM lessons_learned WHERE experiment_id = ? ORDER BY created_at",
            (experiment_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_lessons(category: str | None = None, confidence: str | None = None,
                 limit: int = 100, db_path: Path = DB_PATH) -> list[dict]:
    clauses, vals = [], []
    if category:
        clauses.append("category = ?")
        vals.append(category)
    if confidence:
        clauses.append("confidence = ?")
        vals.append(confidence)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    vals.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM lessons_learned {where} ORDER BY created_at DESC LIMIT ?",
            vals,
        ).fetchall()
        return [dict(r) for r in rows]


def get_high_confidence_lessons(db_path: Path = DB_PATH) -> list[dict]:
    return list_lessons(confidence="high", db_path=db_path)


def lessons_for_idea_generator(db_path: Path = DB_PATH) -> list[dict]:
    """
    Returns lessons the Idea Generator should consult when proposing a hypothesis.
    Ordered by confidence (high first), then recency.
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM lessons_learned
            ORDER BY
                CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def lesson_summary(db_path: Path = DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM lessons_learned").fetchone()[0]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) AS n FROM lessons_learned GROUP BY category"
        ).fetchall()
        by_conf = conn.execute(
            "SELECT confidence, COUNT(*) AS n FROM lessons_learned GROUP BY confidence"
        ).fetchall()
        return {
            "total": total,
            "by_category": {r["category"]: r["n"] for r in by_cat},
            "by_confidence": {r["confidence"]: r["n"] for r in by_conf},
        }
