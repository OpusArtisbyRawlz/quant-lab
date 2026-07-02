"""
bars.builder — the single public entry point of the Bar Engine.

``BarEngine.build(raw_data, sampling_spec)`` is a **pure, deterministic**
function: same inputs → same ``BarResult``, with no I/O, no randomness, and no
mutation of the caller's data. The executor (M7) calls this and nothing else; it
never needs to know how any bar type is constructed.

Dispatch is total over the recognised vocabulary: a recognised-but-unimplemented
bar type raises ``NotImplementedError`` (never silently wrong bars); an
unrecognised type is rejected by ``SamplingSpec`` construction.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import (
    BarResult,
    SamplingSpec,
    IMPLEMENTED_BAR_TYPES,
)
from .validation import validate_bars
from .time import build_time_bars


def _coerce_spec(sampling_spec: SamplingSpec | str | None) -> SamplingSpec:
    """Accept a full SamplingSpec, a bare bar-type string, or None (→ time)."""
    if sampling_spec is None:
        return SamplingSpec()  # default: time
    if isinstance(sampling_spec, SamplingSpec):
        return sampling_spec
    if isinstance(sampling_spec, str):
        return SamplingSpec.from_bar_type(sampling_spec)
    raise TypeError(
        f"sampling_spec must be SamplingSpec | str | None, got {type(sampling_spec).__name__}"
    )


class BarEngine:
    """Deterministic market-sampling engine. Stateless; all methods are pure."""

    @staticmethod
    def build(
        raw_data: dict[str, pd.DataFrame],
        sampling_spec: SamplingSpec | str | None = None,
    ) -> BarResult:
        """Sample ``raw_data`` onto the clock described by ``sampling_spec``.

        Parameters
        ----------
        raw_data:
            ``ticker -> DataFrame`` of OHLCV bars (DatetimeIndex).
        sampling_spec:
            A ``SamplingSpec``, a bar-type string (e.g. ``"time"``), or ``None``
            for the default time clock.

        Returns
        -------
        BarResult
        """
        spec = _coerce_spec(sampling_spec)
        diagnostics: dict[str, Any] = validate_bars(raw_data)

        if spec.type not in IMPLEMENTED_BAR_TYPES:
            raise NotImplementedError(
                f"bar_type {spec.type!r} is recognised but not implemented in "
                f"BE-1; implemented: {sorted(IMPLEMENTED_BAR_TYPES)}"
            )

        # --- dispatch (time only in BE-1) --------------------------------
        data, periods_per_year = build_time_bars(raw_data, spec)

        diagnostics.update({
            "bar_type": spec.type,
            "periods_per_year": periods_per_year,
            "identity": spec.type == "time",
        })
        return BarResult(
            data=data,
            periods_per_year=periods_per_year,
            sampling_spec=spec,
            diagnostics=diagnostics,
        )


def build(
    raw_data: dict[str, pd.DataFrame],
    sampling_spec: SamplingSpec | str | None = None,
) -> BarResult:
    """Module-level convenience wrapper around ``BarEngine.build``."""
    return BarEngine.build(raw_data, sampling_spec)
