"""
bars.defaults — data-derived default thresholds for event bars.

Event builders (tick / volume / dollar and their imbalance variants) need a
``params["threshold"]``. During experimentation callers pass one explicitly, but
for **production/routine** use the executor hands the engine only a bare bar-type
string (``ExperimentSpec.bar_type``) with no tuned threshold. Rather than push
threshold-selection into the executor — which must stay bar-agnostic — the engine
derives a sensible default **from the data itself** when none is supplied.

Policy
------
Aim for a target number of bars per ticker (``TARGET_BARS_PER_TICKER``) so the
resulting cross-section has a usable length regardless of the raw sampling
frequency. Thresholds are pooled across the whole ``ticker -> DataFrame`` bundle
so every ticker is sampled on the *same* scale (a single scalar threshold applies
to all tickers, exactly as an explicit threshold would):

    tick    : rows-per-bar   = total_rows / (n_tickers * target)
    volume  : Σ Volume       / (n_tickers * target)
    dollar  : Σ Close*Volume / (n_tickers * target)

Imbalance variants reuse the same scale as their non-imbalance counterpart; the
signed accumulator crosses less often, so they naturally yield fewer, larger
bars — acceptable for a default that a researcher can always override.

Determinism & purity
--------------------
A pure function of the input frames: no I/O, no randomness, no mutation. An
explicit ``params["threshold"]`` always wins, so this never changes a tuned run.
"""

from __future__ import annotations

import pandas as pd

# Target number of event bars per ticker when deriving a default threshold. Big
# enough to leave a workable cross-sectional time series, small enough that each
# bar aggregates several raw observations (the point of event sampling).
TARGET_BARS_PER_TICKER: int = 50

# Which underlying accumulator each bar type integrates. Imbalance variants share
# the scale of their base weight.
_VOLUME_KINDS = frozenset({"volume", "volume_imbalance"})
_DOLLAR_KINDS = frozenset({"dollar", "dollar_imbalance"})
_TICK_KINDS = frozenset({"tick", "tick_imbalance"})


def default_threshold(
    bar_type: str,
    raw_data: dict[str, pd.DataFrame],
    *,
    target_bars_per_ticker: int = TARGET_BARS_PER_TICKER,
) -> float:
    """Derive a pooled default threshold for ``bar_type`` from ``raw_data``.

    Returns a positive float. ``tick`` thresholds are whole rows-per-bar (still
    returned as a float; callers cast as needed). Raises ``ValueError`` for a bar
    type that has no accumulator scale (e.g. ``time``) or for empty data.
    """
    if not raw_data:
        raise ValueError("cannot derive a default threshold from empty data")
    n_tickers = len(raw_data)
    target = max(1, int(target_bars_per_ticker))
    denom = n_tickers * target

    if bar_type in _TICK_KINDS:
        total_rows = sum(len(df) for df in raw_data.values())
        return float(max(1, round(total_rows / denom)))

    if bar_type in _VOLUME_KINDS:
        total = sum(float(df["Volume"].to_numpy(dtype=float).sum()) for df in raw_data.values())
    elif bar_type in _DOLLAR_KINDS:
        total = sum(
            float((df["Close"].to_numpy(dtype=float) * df["Volume"].to_numpy(dtype=float)).sum())
            for df in raw_data.values()
        )
    else:
        raise ValueError(f"no default-threshold scale for bar_type {bar_type!r}")

    if total <= 0:
        raise ValueError(f"non-positive accumulator total for {bar_type!r}; cannot derive threshold")
    return total / denom


def resolve_threshold(
    bar_type: str, spec_threshold, raw_data: dict[str, pd.DataFrame]
) -> float:
    """An explicit ``spec_threshold`` if given, else a data-derived default.

    Centralises the "tuned value wins, otherwise measure from data" policy so all
    event builders share one code path.
    """
    if spec_threshold is not None:
        return float(spec_threshold)
    return default_threshold(bar_type, raw_data)
