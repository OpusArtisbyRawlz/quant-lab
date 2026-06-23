"""
HypothesisTreeManager — Milestone 10 PR-2 hypothesis-evolution agent.

Deterministic. No LLM. The HypothesisTreeManager is the *sole writer* of the
``hypothesis_node`` and ``hypothesis_edge`` tables. It records how research
hypotheses evolve within a campaign as an append-only tree (a DAG once two
lineages are merged by ``combine``).

Guarantees
----------
* **Every node is fully auditable.** Each node is an immutable row carrying its
  campaign, primary parent, root, depth, hypothesis text, signals/context, and
  the evolution operator that produced it. Nodes are never updated in place
  (idea/experiment links are write-once stamps), so the whole tree is
  reconstructible from storage at any time.
* **Every child records its parent.** A non-root node always has parent_id set,
  and every parent→child relationship is also written as an explicit
  ``hypothesis_edge`` labelled with the operator.
* **Every edge records the evolution operator** — one of the six fixed operators
  below. ``combine`` records one edge per merged parent into the single child;
  every other operator records exactly one edge.

This module never touches execution logic, the approval flow, or experiment
storage. It only models the hypothesis lineage; an idea/experiment is linked to
a node by a write-once stamp after it is created elsewhere.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agents.storage.db import DB_PATH
from agents.storage import hypothesis_store

# The six fixed evolution operators. An edge's operator must be one of these.
OP_REFINE = "refine"
OP_VARY_BAR = "vary_bar"
OP_CROSS_MARKET = "cross_market"
OP_ADD_FILTER = "add_filter"
OP_COMBINE = "combine"
OP_NEGATE = "negate"

VALID_OPERATORS = frozenset(
    {OP_REFINE, OP_VARY_BAR, OP_CROSS_MARKET, OP_ADD_FILTER, OP_COMBINE, OP_NEGATE}
)

# Operators that derive a child from a single parent (everything except combine).
SINGLE_PARENT_OPERATORS = VALID_OPERATORS - {OP_COMBINE}


class HypothesisTreeError(RuntimeError):
    """Raised on an invalid tree operation (unknown node, bad operator, etc.)."""


@dataclass
class TreeNode:
    """A reconstructed node plus its children (primary-parent spanning tree)."""
    node: dict[str, Any]
    children: list["TreeNode"]

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.node)
        d["children"] = [c.to_dict() for c in self.children]
        return d


def _gen_node_id() -> str:
    return "hyp_" + uuid.uuid4().hex[:12]


class HypothesisTreeManager:
    """Owns the hypothesis tree. Sole writer of hypothesis_node/hypothesis_edge."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    # -- construction ------------------------------------------------------

    def create_root(
        self,
        campaign_id: str,
        hypothesis: str,
        *,
        node_id: str | None = None,
        signals: Any = None,
        market: str | None = None,
        universe: str | None = None,
        bar_type: str = "time",
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Create a root hypothesis node (parent_id NULL, depth 0, no operator)."""
        node_id = node_id or _gen_node_id()
        if hypothesis_store.get_node(node_id, db_path=self.db_path):
            raise HypothesisTreeError(f"node already exists: {node_id}")
        hypothesis_store.insert_node(
            {
                "node_id": node_id,
                "campaign_id": campaign_id,
                "parent_id": None,
                "root_id": node_id,
                "depth": 0,
                "hypothesis": hypothesis,
                "signals": signals,
                "market": market,
                "universe": universe,
                "bar_type": bar_type,
                "origin_operator": None,
                "rationale": rationale,
            },
            db_path=self.db_path,
        )
        return hypothesis_store.get_node(node_id, db_path=self.db_path)

    def evolve(
        self,
        parent_id: str,
        operator: str,
        hypothesis: str,
        *,
        node_id: str | None = None,
        signals: Any = None,
        market: str | None = None,
        universe: str | None = None,
        bar_type: str | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Derive a child node from a single parent under a single-parent
        operator. Context fields (signals/market/universe/bar_type) default to
        the parent's values when not overridden. Records the node and an edge
        labelled with the operator.

        Use combine() for the multi-parent ``combine`` operator.
        """
        if operator not in SINGLE_PARENT_OPERATORS:
            raise HypothesisTreeError(
                f"operator must be one of {sorted(SINGLE_PARENT_OPERATORS)} "
                f"(use combine() for 'combine'): got {operator!r}"
            )
        parent = hypothesis_store.get_node(parent_id, db_path=self.db_path)
        if parent is None:
            raise HypothesisTreeError(f"unknown parent node: {parent_id}")

        node_id = node_id or _gen_node_id()
        if hypothesis_store.get_node(node_id, db_path=self.db_path):
            raise HypothesisTreeError(f"node already exists: {node_id}")

        child = {
            "node_id": node_id,
            "campaign_id": parent["campaign_id"],
            "parent_id": parent_id,
            "root_id": parent["root_id"],
            "depth": parent["depth"] + 1,
            "hypothesis": hypothesis,
            "signals": signals if signals is not None else parent.get("signals"),
            "market": market if market is not None else parent.get("market"),
            "universe": universe if universe is not None else parent.get("universe"),
            "bar_type": bar_type if bar_type is not None else parent.get("bar_type", "time"),
            "origin_operator": operator,
            "rationale": rationale,
        }
        hypothesis_store.insert_node(child, db_path=self.db_path)
        hypothesis_store.insert_edge(
            {
                "campaign_id": parent["campaign_id"],
                "parent_id": parent_id,
                "child_id": node_id,
                "operator": operator,
                "rationale": rationale,
            },
            db_path=self.db_path,
        )
        return hypothesis_store.get_node(node_id, db_path=self.db_path)

    def combine(
        self,
        parent_ids: list[str],
        hypothesis: str,
        *,
        node_id: str | None = None,
        signals: Any = None,
        market: str | None = None,
        universe: str | None = None,
        bar_type: str | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Merge two or more parent hypotheses into one child under the
        ``combine`` operator. The first parent is the child's primary parent
        (recorded in node.parent_id and root_id); a ``combine`` edge is written
        from every parent into the child.
        """
        if len(parent_ids) < 2:
            raise HypothesisTreeError("combine requires at least two parents")
        parents = []
        for pid in parent_ids:
            p = hypothesis_store.get_node(pid, db_path=self.db_path)
            if p is None:
                raise HypothesisTreeError(f"unknown parent node: {pid}")
            parents.append(p)

        primary = parents[0]
        node_id = node_id or _gen_node_id()
        if hypothesis_store.get_node(node_id, db_path=self.db_path):
            raise HypothesisTreeError(f"node already exists: {node_id}")

        child = {
            "node_id": node_id,
            "campaign_id": primary["campaign_id"],
            "parent_id": primary["node_id"],
            "root_id": primary["root_id"],
            "depth": max(p["depth"] for p in parents) + 1,
            "hypothesis": hypothesis,
            "signals": signals,
            "market": market if market is not None else primary.get("market"),
            "universe": universe if universe is not None else primary.get("universe"),
            "bar_type": bar_type if bar_type is not None else primary.get("bar_type", "time"),
            "origin_operator": OP_COMBINE,
            "rationale": rationale,
        }
        hypothesis_store.insert_node(child, db_path=self.db_path)
        for p in parents:
            hypothesis_store.insert_edge(
                {
                    "campaign_id": primary["campaign_id"],
                    "parent_id": p["node_id"],
                    "child_id": node_id,
                    "operator": OP_COMBINE,
                    "rationale": rationale,
                },
                db_path=self.db_path,
            )
        return hypothesis_store.get_node(node_id, db_path=self.db_path)

    # -- write-once links --------------------------------------------------

    def link_idea(self, node_id: str, idea_id: str) -> None:
        if hypothesis_store.get_node(node_id, db_path=self.db_path) is None:
            raise HypothesisTreeError(f"unknown node: {node_id}")
        hypothesis_store.link_node_idea(node_id, idea_id, db_path=self.db_path)

    def link_experiment(self, node_id: str, experiment_id: str) -> None:
        if hypothesis_store.get_node(node_id, db_path=self.db_path) is None:
            raise HypothesisTreeError(f"unknown node: {node_id}")
        hypothesis_store.link_node_experiment(
            node_id, experiment_id, db_path=self.db_path
        )

    # -- reads / reconstruction -------------------------------------------

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        return hypothesis_store.get_node(node_id, db_path=self.db_path)

    def lineage(self, node_id: str) -> list[dict[str, Any]]:
        """The primary-parent path from the root down to node_id (inclusive),
        reconstructed purely from stored parent_id links."""
        chain: list[dict[str, Any]] = []
        cur = hypothesis_store.get_node(node_id, db_path=self.db_path)
        if cur is None:
            raise HypothesisTreeError(f"unknown node: {node_id}")
        while cur is not None:
            chain.append(cur)
            pid = cur.get("parent_id")
            cur = hypothesis_store.get_node(pid, db_path=self.db_path) if pid else None
        chain.reverse()
        return chain

    def reconstruct_tree(self, root_id: str) -> TreeNode:
        """Rebuild a single tree (primary-parent spanning tree) from storage,
        starting at root_id. Children are ordered by depth then creation."""
        root = hypothesis_store.get_node(root_id, db_path=self.db_path)
        if root is None:
            raise HypothesisTreeError(f"unknown root node: {root_id}")
        campaign_id = root["campaign_id"]
        nodes = hypothesis_store.list_nodes(campaign_id, db_path=self.db_path)
        # Index children by primary parent_id, restricted to this root's tree.
        by_parent: dict[str, list[dict[str, Any]]] = {}
        for n in nodes:
            if n["root_id"] != root_id:
                continue
            pid = n.get("parent_id")
            if pid is not None:
                by_parent.setdefault(pid, []).append(n)

        def build(node: dict[str, Any]) -> TreeNode:
            kids = by_parent.get(node["node_id"], [])
            return TreeNode(node=node, children=[build(k) for k in kids])

        return build(root)

    def reconstruct_forest(self, campaign_id: str) -> list[TreeNode]:
        """Rebuild every tree in a campaign from storage, one per root node."""
        roots = hypothesis_store.list_roots(campaign_id, db_path=self.db_path)
        return [self.reconstruct_tree(r["node_id"]) for r in roots]

    def edges(self, campaign_id: str) -> list[dict[str, Any]]:
        return hypothesis_store.list_edges(campaign_id, db_path=self.db_path)

    def parents_of(self, node_id: str) -> list[dict[str, Any]]:
        return hypothesis_store.parents_of(node_id, db_path=self.db_path)
