"""
agents.recovery — Historical Strategy Recovery support.

A thin, deterministic data layer over a curated manifest of the historical strategies
in Projects 03-06 (`historical_strategies.json`). It introduces NO research logic and
NO new agent: it only reads the reviewed manifest and exposes it for enumeration,
verification, and the recovery HypothesisSource. The manifest is operator-curated and
reviewed before any recovery campaign runs.
"""

from .manifest import (
    load_manifest,
    enumerate_strategies,
    strategies_for_kind,
    projects_covered,
    verify_enumeration,
    RECOVERY_PROJECTS,
    KIND_BASELINE,
    KIND_BLEND,
    KIND_OVERLAY,
    KIND_DEPLOYMENT,
)

__all__ = [
    "load_manifest",
    "enumerate_strategies",
    "strategies_for_kind",
    "projects_covered",
    "verify_enumeration",
    "RECOVERY_PROJECTS",
    "KIND_BASELINE",
    "KIND_BLEND",
    "KIND_OVERLAY",
    "KIND_DEPLOYMENT",
]
