"""
memory_store — reads and writes the Milestone 9 research_memory table.

research_memory holds distilled cross-experiment findings, each scoped to a
context tuple or roll-up level (`scope_key`). It is the durable "what have we
learned about signals in this context" layer the IdeaGenerator consults
alongside lessons_learned.

The `embedding` column is intentionally left NULL on the offline/test path:
semantic-similarity dedup of memory is deferred (TD-5). Insertion is idempotent
on (scope_key, finding) so re-running the librarian never duplicates a memory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .db import get_connection, DB_PATH


def add_memory(scope_key: str, finding: str, *,
               implication: str = "", confidence: str = "medium",
               db_path: Path = DB_PATH) -> None:
    """Insert a memory; idempotent on (scope_key, finding)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO research_memory
                (scope_key, finding, implication, confidence, embedding, created_at)
            VALUES (?, ?, ?, ?, NULL, ?)
            ON CONFLICT(scope_key, finding)
            DO UPDATE SET implication = excluded.implication,
                          confidence = excluded.confidence
            """,
            (scope_key, finding, implication, confidence, now),
        )
        conn.commit()


def list_memory(scope_key: str | None = None, limit: int = 200,
                db_path: Path = DB_PATH) -> list[dict]:
    clauses, vals = [], []
    if scope_key is not None:
        clauses.append("scope_key = ?")
        vals.append(scope_key)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    vals.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM research_memory {where} "
            f"ORDER BY created_at DESC LIMIT ?",
            vals,
        ).fetchall()
        return [dict(r) for r in rows]


def memory_for_idea_generator(db_path: Path = DB_PATH,
                              limit: int = 50) -> list[dict]:
    """Memories the IdeaGenerator should consult, most recent first."""
    return list_memory(scope_key=None, limit=limit, db_path=db_path)
