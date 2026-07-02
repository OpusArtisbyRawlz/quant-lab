"""
Bar Engine — a deterministic, reusable market-sampling module.

Public surface:

    from src.data.bars import BarEngine, SamplingSpec, BarResult, build

    result = BarEngine.build(raw_data, SamplingSpec(type="time"))
    bars = result.data                       # ticker -> DataFrame
    ppy  = result.periods_per_year           # annualisation cadence

The engine is execution-layer infrastructure, not an agent: it makes no
decisions, holds no state, performs no I/O, and depends on nothing in the agent,
M9, or M10 layers. Every research project is expected to obtain its bars through
this one component.

BE-1 ships identity/time sampling only; the vocabulary for tick / volume /
dollar / imbalance bars is defined but their builders arrive in later PRs.
"""

from __future__ import annotations

from .base import (
    SamplingSpec,
    BarResult,
    BAR_TYPES,
    IMPLEMENTED_BAR_TYPES,
    DEFAULT_PERIODS_PER_YEAR,
    REQUIRED_COLUMNS,
)
from .validation import validate_bars, BarValidationError
from .builder import BarEngine, build

__all__ = [
    "BarEngine",
    "build",
    "SamplingSpec",
    "BarResult",
    "validate_bars",
    "BarValidationError",
    "BAR_TYPES",
    "IMPLEMENTED_BAR_TYPES",
    "DEFAULT_PERIODS_PER_YEAR",
    "REQUIRED_COLUMNS",
]
