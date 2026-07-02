"""
bars.time — the time (calendar) sampling clock.

BE-1 implements the **identity** case: the input is already time-sampled
(daily) OHLCV, so time bars are a faithful pass-through. Each frame is copied so
the engine never mutates its caller's data (purity), and no values, index, or
columns are altered — this is what guarantees byte-identical downstream results
vs. the pre-engine pipeline.

Calendar down-sampling (e.g. daily → weekly via a ``freq`` param) is a deliberate
non-goal for BE-1 and will land in a later PR; it does not affect the default
identity path.
"""

from __future__ import annotations

import pandas as pd

from .base import SamplingSpec, DEFAULT_PERIODS_PER_YEAR


def build_time_bars(
    raw_data: dict[str, pd.DataFrame], spec: SamplingSpec
) -> tuple[dict[str, pd.DataFrame], float]:
    """Identity time-bar construction.

    Returns
    -------
    (data, periods_per_year)
        ``data`` is a per-ticker deep-ish copy of the input (faithful, unmutated).
        ``periods_per_year`` is the spec override if given, else 252 (daily).
    """
    if spec.param("freq") is not None:
        raise NotImplementedError(
            "calendar down-sampling (freq) is not implemented in BE-1; "
            "time bars are identity pass-through only"
        )
    out = {ticker: df.copy(deep=True) for ticker, df in raw_data.items()}
    periods_per_year = spec.periods_per_year or DEFAULT_PERIODS_PER_YEAR
    return out, periods_per_year
