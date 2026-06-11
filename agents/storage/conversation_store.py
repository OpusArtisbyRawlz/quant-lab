"""
Agent conversation log — reads and writes the agent_conversations table.

Every message passed between agents in a research cycle is persisted here.
This provides a full audit trail and lets future agents replay or summarise
past reasoning chains.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def log_message(
    cycle_id: str,
    sender: str,
    recipient: str,
    message_type: str,
    payload: dict[str, Any],
    db_path: Path = DB_PATH,
) -> int:
    """Persist one agent message. Returns the new row id."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_conversations
                (cycle_id, sender, recipient, message_type, payload, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                cycle_id,
                sender,
                recipient,
                message_type,
                json.dumps(payload),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def log_many(messages: list[dict[str, Any]], db_path: Path = DB_PATH) -> int:
    """Bulk-insert messages. Each dict must have keys: cycle_id, sender, recipient, message_type, payload."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            m["cycle_id"],
            m["sender"],
            m["recipient"],
            m["message_type"],
            json.dumps(m["payload"]),
            m.get("timestamp", now),
        )
        for m in messages
    ]
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO agent_conversations
                (cycle_id, sender, recipient, message_type, payload, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_cycle_messages(cycle_id: str, db_path: Path = DB_PATH) -> list[dict]:
    """Return all messages for a cycle in chronological order."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM agent_conversations WHERE cycle_id = ? ORDER BY timestamp",
            (cycle_id,),
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


def get_messages_by_type(cycle_id: str, message_type: str,
                          db_path: Path = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM agent_conversations "
            "WHERE cycle_id = ? AND message_type = ? ORDER BY timestamp",
            (cycle_id, message_type),
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]


def list_cycles(db_path: Path = DB_PATH) -> list[str]:
    """Return distinct cycle_ids ordered by first message timestamp."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT cycle_id, MIN(timestamp) AS first_msg "
            "FROM agent_conversations GROUP BY cycle_id ORDER BY first_msg DESC"
        ).fetchall()
        return [r["cycle_id"] for r in rows]


def get_latest_cycle(db_path: Path = DB_PATH) -> str | None:
    cycles = list_cycles(db_path)
    return cycles[0] if cycles else None


def conversation_summary(db_path: Path = DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM agent_conversations").fetchone()[0]
        cycles = conn.execute(
            "SELECT COUNT(DISTINCT cycle_id) FROM agent_conversations"
        ).fetchone()[0]
        by_type = conn.execute(
            "SELECT message_type, COUNT(*) AS n FROM agent_conversations GROUP BY message_type"
        ).fetchall()
        by_sender = conn.execute(
            "SELECT sender, COUNT(*) AS n FROM agent_conversations GROUP BY sender"
        ).fetchall()
        return {
            "total_messages": total,
            "total_cycles": cycles,
            "by_type": {r["message_type"]: r["n"] for r in by_type},
            "by_sender": {r["sender"]: r["n"] for r in by_sender},
        }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _deserialize(record: dict[str, Any]) -> dict[str, Any]:
    if "payload" in record and isinstance(record["payload"], str):
        try:
            record["payload"] = json.loads(record["payload"])
        except (json.JSONDecodeError, TypeError):
            pass
    return record
