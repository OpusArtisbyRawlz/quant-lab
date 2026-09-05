"""
Milestone 11 — Research Intelligence.

A pure *read-and-decide* evidence layer over the existing agent seams. It changes
research **decisions**, not models or execution. See
``docs/M11_RESEARCH_INTELLIGENCE_DESIGN.md`` (frozen M11-0 baseline) and
``docs/M11_STATISTICAL_METHODOLOGY.md``.

PR-1 (this package's first slice) ships only the durable **evidence capture**
layer: ``EvidenceRecorder`` turns a finished experiment into one immutable,
fully-provenanced ``evidence_event``. It records evidence and nothing else — no
promotion, retirement, confidence, or deployment decision is made here.
"""

from __future__ import annotations

from .evidence_recorder import EvidenceRecorder
from .evidence_projector import EvidenceProjector
from .promotion_engine import PromotionEngine
from .holdout_engine import HoldoutEngine
from .fdr_engine import FdrEngine
from .retirement_engine import RetirementEngine
from .budget_engine import BudgetEngine
from . import statistics
from . import promotion
from . import holdout
from . import fdr
from . import retirement
from . import budget
from . import decision

__all__ = [
    "EvidenceRecorder", "EvidenceProjector", "PromotionEngine", "HoldoutEngine",
    "FdrEngine", "RetirementEngine", "BudgetEngine",
    "statistics", "promotion", "holdout", "fdr", "retirement", "budget", "decision",
]
