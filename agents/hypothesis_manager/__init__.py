"""hypothesis_manager — Milestone 10 hypothesis-evolution tree agent."""

from .manager import (
    HypothesisTreeManager,
    HypothesisTreeError,
    TreeNode,
    VALID_OPERATORS,
    SINGLE_PARENT_OPERATORS,
    OP_REFINE,
    OP_VARY_BAR,
    OP_CROSS_MARKET,
    OP_ADD_FILTER,
    OP_COMBINE,
    OP_NEGATE,
)

__all__ = [
    "HypothesisTreeManager",
    "HypothesisTreeError",
    "TreeNode",
    "VALID_OPERATORS",
    "SINGLE_PARENT_OPERATORS",
    "OP_REFINE",
    "OP_VARY_BAR",
    "OP_CROSS_MARKET",
    "OP_ADD_FILTER",
    "OP_COMBINE",
    "OP_NEGATE",
]
