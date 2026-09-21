"""
composite.py — first-class multi-strategy portfolio composition.

A general, additive capability: combine several existing strategy return streams into
one portfolio return stream, without duplicating any execution logic. Child strategies
still execute through the normal factory pipeline; this module only defines the
portfolio *shape* (``PortfolioSpec``) and the pure composition math (weighted combine).
Per-child and portfolio-level overlays reuse the existing ``src/risk`` code via the
executor — nothing here recomputes a child signal.

Deterministic by construction: children are composed in a fixed, sorted order and the
weighted sum aligns on the shared date index, so replay is byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import pandas as pd


@dataclass
class PortfolioChild:
    """One child in a composite portfolio.

    Exactly one of ``features`` (a leaf signal book, executed via the normal
    cross-sectional pipeline) or ``portfolio`` (a nested composite) must be set.
    ``weight`` is the fixed portfolio weight. ``overlay`` is an optional per-child
    return-level overlay (e.g. smooth-DD); ``weight_overlay`` is an optional per-child
    weight-level overlay (e.g. a vol-regime exposure) applied to the child's panel
    weights before its returns are formed.
    """
    child_id: str
    weight: float
    features: list[str] | None = None
    portfolio: "PortfolioSpec | None" = None
    overlay: dict[str, Any] | None = None
    weight_overlay: dict[str, Any] | None = None

    def is_leaf(self) -> bool:
        return self.features is not None and self.portfolio is None


@dataclass
class PortfolioSpec:
    """A composite portfolio of child strategy return streams.

    ``weighting`` currently supports only ``"fixed"`` (historical recovery needs no
    optimiser). ``overlay`` is the optional portfolio-level overlay applied *after*
    child composition. ``rebalance`` records the historical convention ("daily").
    ``start``/``end`` are the effective date range (informational; the shared child
    index governs alignment). ``provenance`` carries the immutable origin chain.
    """
    portfolio_id: str
    children: list[PortfolioChild]
    universe: str = ""
    weighting: str = "fixed"
    overlay: dict[str, Any] | None = None
    rebalance: str = "daily"
    start: str = ""
    end: str = ""
    provenance: dict[str, Any] | None = None

    # ---- validation + deterministic ordering --------------------------------
    def validate(self) -> None:
        if not self.children:
            raise ValueError("PortfolioSpec.children must be non-empty")
        ids = [c.child_id for c in self.children]
        if len(ids) != len(set(ids)):
            raise ValueError(f"child_id values must be unique: {ids}")
        for c in self.children:
            if (c.features is None) == (c.portfolio is None):
                raise ValueError(
                    f"child {c.child_id!r}: set exactly one of features / portfolio")
            if not isinstance(c.weight, (int, float)) or c.weight != c.weight:
                raise ValueError(f"child {c.child_id!r}: weight must be a number")
        if self.weighting != "fixed":
            raise ValueError(f"unsupported weighting mode: {self.weighting!r}")
        total = sum(c.weight for c in self.children)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"fixed weights must sum to 1.0 (got {total}) for {self.portfolio_id}")

    def ordered_children(self) -> list[PortfolioChild]:
        """Children in deterministic order (sorted by child_id) — the order used for
        composition, so the result never depends on manifest/list ordering."""
        return sorted(self.children, key=lambda c: c.child_id)

    # ---- (de)serialisation for idea metadata / spec transport ---------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PortfolioSpec":
        children = [
            PortfolioChild(
                child_id=c["child_id"], weight=c["weight"],
                features=c.get("features"),
                portfolio=PortfolioSpec.from_dict(c["portfolio"]) if c.get("portfolio") else None,
                overlay=c.get("overlay"), weight_overlay=c.get("weight_overlay"),
            )
            for c in d["children"]
        ]
        return PortfolioSpec(
            portfolio_id=d["portfolio_id"], children=children,
            universe=d.get("universe", ""), weighting=d.get("weighting", "fixed"),
            overlay=d.get("overlay"), rebalance=d.get("rebalance", "daily"),
            start=d.get("start", ""), end=d.get("end", ""),
            provenance=d.get("provenance"),
        )


def combine_returns(streams: list[tuple[str, pd.Series, float]]) -> pd.Series:
    """Weighted sum of child return streams: Σ weightᵢ · returnᵢ.

    ``streams`` is a list of (child_id, return_series, weight) in the caller's already
    deterministic order. Streams are aligned on their shared date index (pandas
    alignment); the caller guarantees children share a universe/date grid, so the
    result carries exactly those dates. Deterministic and pure.
    """
    if not streams:
        raise ValueError("combine_returns: no child streams")
    combined: pd.Series | None = None
    for _cid, ret, w in streams:
        term = ret * float(w)
        combined = term if combined is None else combined.add(term, fill_value=0.0)
    return combined
