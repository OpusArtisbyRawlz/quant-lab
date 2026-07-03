"""
bars.periods — realised annualisation cadence for irregular bars.

Metrics such as the Sharpe ratio annualise a per-period return series by a
*periods-per-year* factor (``sharpe = sqrt(ppy) * mean / std``). Daily time bars
have a well-known cadence of 252 trading periods per year, but event bars
(tick / volume / dollar / imbalance) close at **irregular, data-driven**
timestamps — far fewer bars in quiet stretches, more when the market is active —
so annualising them with 252 would badly misstate their risk-adjusted metrics.

``realized_periods_per_year`` derives the cadence from the bars themselves: how
many bar-intervals actually elapsed per calendar year across the panel.

Definition
----------
For each ticker with sorted bar-close timestamps ``t_0 < t_1 < ... < t_{n-1}``
there are ``n - 1`` intervals spanning ``t_{n-1} - t_0`` of calendar time. The
panel-level cadence pools these across tickers::

    ppy = DAYS_PER_YEAR * (Σ intervals) / (Σ span_in_days)

i.e. the total number of bar-intervals observed divided by the total calendar
time they cover, expressed per year. Pooling (rather than averaging per-ticker
rates) weights each ticker by the calendar span it actually contributes, and is
robust to a ticker that produced only one bar (it adds zero intervals and zero
span). If no ticker has two or more bars — no interval exists to measure — the
cadence is undefined and the caller's ``default`` (252) is returned.

Purity
------
No I/O, no randomness, never mutates its input. A pure function of the bar-close
timestamps only.
"""

from __future__ import annotations

import pandas as pd

from .base import DEFAULT_PERIODS_PER_YEAR, SamplingSpec

# Mean length of the Gregorian year in days (accounts for leap years). Using a
# fixed constant keeps the computation deterministic and independent of which
# particular years the data happens to span.
DAYS_PER_YEAR: float = 365.25


def realized_periods_per_year(
    bars: dict[str, pd.DataFrame], *, default: float = DEFAULT_PERIODS_PER_YEAR
) -> float:
    """Realised bars-per-year cadence pooled across every ticker.

    Parameters
    ----------
    bars:
        ``ticker -> DataFrame`` of bars, each with a sorted DatetimeIndex of
        bar-close timestamps.
    default:
        Returned when the cadence cannot be measured (no ticker has at least two
        bars, or the total span is non-positive). Defaults to 252.

    Returns
    -------
    float
        Positive periods-per-year estimate, or ``default`` when undefined.
    """
    total_intervals = 0
    total_span_days = 0.0
    for df in bars.values():
        idx = df.index
        if len(idx) < 2:
            continue
        idx = idx.sort_values()
        span_days = (idx[-1] - idx[0]).total_seconds() / 86_400.0
        if span_days <= 0:
            continue
        total_intervals += len(idx) - 1
        total_span_days += span_days

    if total_intervals == 0 or total_span_days <= 0:
        return float(default)
    return DAYS_PER_YEAR * total_intervals / total_span_days


def event_periods_per_year(
    spec: SamplingSpec, bars: dict[str, pd.DataFrame]
) -> float:
    """Resolve the annualisation cadence for a set of event bars.

    An explicit ``spec.periods_per_year`` always wins (the caller has stated the
    cadence). Otherwise it is *measured* from the produced bars via
    :func:`realized_periods_per_year`. This is the single point every event-bar
    builder uses so the realised-cadence policy lives in one place; time bars do
    not call it and keep their fixed 252 (byte-identical production path).
    """
    return spec.periods_per_year or realized_periods_per_year(bars)
