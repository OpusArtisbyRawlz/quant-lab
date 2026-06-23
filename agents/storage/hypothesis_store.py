"""
hypothesis_store — reads and writes the Milestone 10 hypothesis-tree tables.

Two append-only tables model how research hypotheses evolve within a campaign:

    hypothesis_node  — one immutable row per hypothesis. The root has parent_id
                       NULL; every other node records its primary parent and the
                       evolution operator that produced it. Nodes are never
                       updated in place (the optional idea_id/experiment_id links
                       are stamped once), so a tree is fully reconstructible.
    hypothesis_edge  — the immutable parent -> child evolution relationship under
                       a named operator. `combine` yields multiple edges into one
                       child; every other operator yields exactly one.

This module is the low-level data-access layer. All tree-construction logic
(operator validity, parent/depth bookkeeping, reconstruction) lives in the
HypothesisTreeManager, which is the sole writer of these tables. This module
performs no validation of its own.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _row_to_node(row) -> dict[str, Any]:
    d = dict(row)
    if "signals" in d:
        d["signals"] = _loads(d["signals"])
    return d


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def insert_node(node: dict[str, Any], *, db_path: Path = DB_PATH) -> str:
    """Insert an immutable hypothesis_node. Returns node_id.

    Required keys: node_id, campaign_id, root_id, hypothesis. Optional:
    parent_id, depth, signals, market, universe, bar_type, origin_operator,
    rationale, idea_id, experiment_id. Raises on duplicate node_id (PK).
    """
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO hypothesis_node (
                node_id, campaign_id, parent_id, root_id, depth, hypothesis,
                signals, market, universe, bar_type, origin_operator, rationale,
                idea_id, experiment_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node["node_id"],
                node["campaign_id"],
                node.get("parent_id"),
                node["root_id"],
                int(node.get("depth", 0)),
                node["hypothesis"],
                _dumps(node.get("signals")),
                node.get("market"),
                node.get("universe"),
                node.get("bar_type", "time"),
                node.get("origin_operator"),
                node.get("rationale"),
                node.get("idea_id"),
                node.get("experiment_id"),
                node.get("created_at") or _utcnow(),
            ),
        )
        conn.commit()
    return node["node_id"]


def insert_edge(edge: dict[str, Any], *, db_path: Path = DB_PATH) -> int:
    """Insert an immutable hypothesis_edge. Returns the new row id.

    Required keys: campaign_id, parent_id, child_id, operator. Optional:
    rationale.
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO hypothesis_edge (
                campaign_id, parent_id, child_id, operator, rationale, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge["campaign_id"],
                edge["parent_id"],
                edge["child_id"],
                edge["operator"],
                edge.get("rationale"),
                edge.get("created_at") or _utcnow(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def link_node_idea(node_id: str, idea_id: str, *, db_path: Path = DB_PATH) -> None:
    """Stamp the originating idea on a node (write-once link, not a mutation of
    the hypothesis itself)."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE hypothesis_node SET idea_id=? WHERE node_id=?",
            (idea_id, node_id),
        )
        conn.commit()


def link_node_experiment(
    node_id: str, experiment_id: str, *, db_path: Path = DB_PATH
) -> None:
    """Stamp the resulting experiment on a node (write-once link)."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE hypothesis_node SET experiment_id=? WHERE node_id=?",
            (experiment_id, node_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_node(node_id: str, *, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM hypothesis_node WHERE node_id=?", (node_id,)
        ).fetchone()
    return _row_to_node(row) if row else None


def get_node_by_idea(
    idea_id: str, *, db_path: Path = DB_PATH
) -> dict[str, Any] | None:
    """The hypothesis node whose originating idea is ``idea_id`` (the
    node<->idea link is write-once, so this is unambiguous)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM hypothesis_node WHERE idea_id=? LIMIT 1", (idea_id,)
        ).fetchone()
    return _row_to_node(row) if row else None


def list_nodes(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    """All nodes for a campaign, ordered by creation (root-first within a tree)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM hypothesis_node WHERE campaign_id=? ORDER BY depth, created_at, node_id",
            (campaign_id,),
        ).fetchall()
    return [_row_to_node(r) for r in rows]


def list_edges(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM hypothesis_edge WHERE campaign_id=? ORDER BY id",
            (campaign_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def children_of(node_id: str, *, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Edges whose parent is node_id (one row per child relationship)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM hypothesis_edge WHERE parent_id=? ORDER BY id",
            (node_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def parents_of(node_id: str, *, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Edges whose child is node_id. More than one only for `combine` nodes."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM hypothesis_edge WHERE child_id=? ORDER BY id",
            (node_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_roots(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM hypothesis_node WHERE campaign_id=? AND parent_id IS NULL "
            "ORDER BY created_at, node_id",
            (campaign_id,),
        ).fetchall()
    return [_row_to_node(r) for r in rows]
