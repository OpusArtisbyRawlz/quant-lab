"""
bars.base — vocabulary and immutable data types for the shared Bar Engine.

This module defines *what* a sampling request is (``SamplingSpec``) and *what*
the engine returns (``BarResult``), independent of how any particular bar type
is built. It has no dependency on agents, M9, M10, or any research project — it
is pure infrastructure that every project (02 → 03 → 04 → 05 → …) can reuse.

Design intent (BE-1): the public surface is organised around a configuration
object, not a bare string, so that new sampling algorithms — run bars, range
bars, renko, adaptive, information-driven, custom research bars — slot in as new
``type`` values (plus their own ``params``) without ever changing the engine's
call signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd

# ---------------------------------------------------------------------------
# Sampling vocabulary
# ---------------------------------------------------------------------------

# Every recognised sampling clock. The engine validates against this set so a
# typo can never flow downstream as silent data. This mirrors the M10
# ExperimentSpec vocabulary but is defined independently here (the engine must
# not import from the agent layer) and additionally recognises `tick_imbalance`.
BAR_TYPES: tuple[str, ...] = (
    "time",
    "tick",
    "volume",
    "dollar",
    "tick_imbalance",
    "volume_imbalance",
    "dollar_imbalance",
)

# Bar types actually constructible in this PR. BE-1 ships identity/time only;
# later PRs (BE-3/BE-4) add the event-driven builders. Requesting a recognised
# but not-yet-implemented type raises a clear NotImplementedError rather than
# silently returning wrong bars.
IMPLEMENTED_BAR_TYPES: frozenset[str] = frozenset({"time"})

# Annualisation cadence for daily time bars. Event-driven builders will compute
# and return their own realised cadence instead of this constant.
DEFAULT_PERIODS_PER_YEAR: float = 252.0

# Columns every bar frame must carry. Extra columns are preserved untouched.
REQUIRED_COLUMNS: tuple[str, ...] = ("Open", "High", "Low", "Close", "Volume")


_EMPTY_PARAMS: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class SamplingSpec:
    """Immutable description of HOW to sample raw market data into bars.

    Parameters
    ----------
    type:
        One of ``BAR_TYPES``. Defaults to ``"time"``.
    params:
        Algorithm-specific knobs (e.g. a volume threshold, an imbalance EWMA
        span). Empty for time bars. Stored read-only so the spec is a faithful,
        reproducible record of the request.
    periods_per_year:
        Optional annualisation override. When ``None`` the engine supplies the
        cadence appropriate to the bar type (252 for daily time bars; a realised
        cadence for event-driven bars in later PRs).

    New sampling algorithms are added by extending ``BAR_TYPES`` and giving them
    a builder — this dataclass and ``BarEngine.build`` never need to change.
    """

    type: str = "time"
    params: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_PARAMS)
    periods_per_year: float | None = None

    def __post_init__(self) -> None:
        if self.type not in BAR_TYPES:
            raise ValueError(
                f"unknown sampling type {self.type!r}; "
                f"expected one of {BAR_TYPES}"
            )
        # Freeze params into a read-only mapping so a caller cannot mutate the
        # spec after construction (keeps build() a pure function of its inputs).
        object.__setattr__(
            self, "params", MappingProxyType(dict(self.params or {}))
        )
        if self.periods_per_year is not None and self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive when provided")

    @classmethod
    def from_bar_type(
        cls,
        bar_type: str | None,
        *,
        params: Mapping[str, Any] | None = None,
        periods_per_year: float | None = None,
    ) -> "SamplingSpec":
        """Build a spec from a bare bar-type string (convenience for callers
        that today only carry ``ExperimentSpec.bar_type``). ``None`` / empty →
        the default ``"time"`` clock."""
        return cls(
            type=(bar_type or "time"),
            params=dict(params or {}),
            periods_per_year=periods_per_year,
        )

    def param(self, key: str, default: Any = None) -> Any:
        """Read one algorithm-specific parameter."""
        return self.params.get(key, default)


@dataclass(frozen=True)
class BarResult:
    """What ``BarEngine.build`` returns.

    Attributes
    ----------
    data:
        ``ticker -> DataFrame`` in the SAME shape as the engine's input, now
        sampled onto the requested clock. For time bars this is a faithful copy
        of the input.
    periods_per_year:
        Annualisation cadence for the produced bars — carried explicitly so the
        backtest never has to assume 252 for a non-daily clock.
    sampling_spec:
        The exact request that produced this result (reproducibility).
    diagnostics:
        Per-run, non-authoritative info: bars per ticker, columns, any data
        quality warnings. Safe to log into ``config.json`` alongside bar_type.
    """

    data: dict[str, pd.DataFrame]
    periods_per_year: float
    sampling_spec: SamplingSpec
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
