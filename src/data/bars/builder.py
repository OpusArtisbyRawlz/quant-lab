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

from typing import Callable

from .base import (
    BarResult,
    SamplingSpec,
    IMPLEMENTED_BAR_TYPES,
    PRODUCTION_BAR_TYPES,
)
from .validation import validate_bars
from .time import build_time_bars
from .tick import build_tick_bars
from .volume import build_volume_bars
from .dollar import build_dollar_bars
from .imbalance import (
    build_tick_imbalance_bars,
    build_volume_imbalance_bars,
    build_dollar_imbalance_bars,
)

# Type alias for a bar builder: (raw_data, spec) -> (data, periods_per_year).
_Builder = Callable[..., tuple[dict, float]]

# Total dispatch table over IMPLEMENTED_BAR_TYPES. Adding a new clock is a single
# entry here plus its builder module — no if/elif chains, and callers never
# branch on the bar type. Kept in sync with IMPLEMENTED_BAR_TYPES by a test.
_BUILDERS: dict[str, _Builder] = {
    "time": build_time_bars,
    "tick": build_tick_bars,
    "volume": build_volume_bars,
    "dollar": build_dollar_bars,
    "tick_imbalance": build_tick_imbalance_bars,
    "volume_imbalance": build_volume_imbalance_bars,
    "dollar_imbalance": build_dollar_imbalance_bars,
}


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
        *,
        allow_experimental: bool = False,
    ) -> BarResult:
        """Sample ``raw_data`` onto the clock described by ``sampling_spec``.

        Parameters
        ----------
        raw_data:
            ``ticker -> DataFrame`` of OHLCV bars (DatetimeIndex).
        sampling_spec:
            A ``SamplingSpec``, a bar-type string (e.g. ``"time"``), or ``None``
            for the default time clock.
        allow_experimental:
            When ``False`` (the default, used by the M7 executor and every real
            caller), only ``PRODUCTION_BAR_TYPES`` may be built; requesting an
            implemented-but-not-yet-production clock (e.g. the BE-3 event bars)
            raises ``NotImplementedError``. Unit tests set this ``True`` to
            exercise the event-bar algorithms on synthetic data. This is the
            gate that keeps event bars out of real campaigns.

        Returns
        -------
        BarResult
        """
        spec = _coerce_spec(sampling_spec)
        diagnostics: dict[str, Any] = validate_bars(raw_data)

        if spec.type not in IMPLEMENTED_BAR_TYPES:
            raise NotImplementedError(
                f"bar_type {spec.type!r} is recognised but has no builder yet; "
                f"implemented: {sorted(IMPLEMENTED_BAR_TYPES)}"
            )

        if not allow_experimental and spec.type not in PRODUCTION_BAR_TYPES:
            raise NotImplementedError(
                f"bar_type {spec.type!r} is implemented but not enabled for "
                f"production/real-campaign use; pass allow_experimental=True to "
                f"exercise it. Production-enabled: {sorted(PRODUCTION_BAR_TYPES)}"
            )

        # --- dispatch via the total builder table (no per-type branching) -
        data, periods_per_year = _BUILDERS[spec.type](raw_data, spec)

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
    *,
    allow_experimental: bool = False,
) -> BarResult:
    """Module-level convenience wrapper around ``BarEngine.build``."""
    return BarEngine.build(raw_data, sampling_spec, allow_experimental=allow_experimental)
