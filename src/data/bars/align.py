"""
bars.align — cross-sectional alignment for irregular event bars.

Time bars share a common daily grid, so the cross-sectional alpha pipeline can
``groupby("Date")`` and every group holds one row per ticker. Event bars
(tick / volume / dollar / imbalance) close at **per-ticker, irregular**
timestamps, so a naive stack-and-group would put ~one ticker in each group and
destroy the cross-section.

``align_cross_section`` fixes this deterministically with **as-of** semantics:

1. Build the sorted **union** of every ticker's bar-close timestamps → a common
   comparison grid.
2. Reindex each ticker onto the grid with forward-fill: at grid time ``t`` a
   ticker takes its most recently *closed* bar at or before ``t`` (no lookahead).
   Grid points before a ticker's first bar are ``NaN`` (that ticker simply isn't
   in the cross-section yet).

The result is a ``ticker -> DataFrame`` bundle where every frame shares the same
index (the grid), so ``build_market_panel`` + ``groupby("Date")`` recovers a
full cross-section at each grid timestamp.

Purity & identity
-----------------
This is a pure function: no I/O, no randomness, never mutates its input. For
bars that already share one grid (e.g. gap-free daily time bars) the union grid
*is* that grid and the forward-fill reindex is the identity — so routing
aligned time bars through the pipeline is byte-identical to today. Alignment is
therefore a no-op for the current production (time) path and is intended for the
event-bar path once those are production-enabled; it is **not** auto-applied
inside ``BarEngine.build``.
"""

from __future__ import annotations

import pandas as pd

# Supported alignment strategies. Only as-of/forward-fill today; kept as a
# vocabulary so future strategies (e.g. drop-to-intersection, interpolate) slot
# in without changing the call signature.
ALIGNMENT_METHODS: tuple[str, ...] = ("asof",)


def align_cross_section(
    bars: dict[str, pd.DataFrame], *, method: str = "asof"
) -> dict[str, pd.DataFrame]:
    """Align irregular per-ticker bars onto a common grid for cross-sectional use.

    Parameters
    ----------
    bars:
        ``ticker -> DataFrame`` of OHLCV bars, each with a (sorted) DatetimeIndex
        of bar-close timestamps. Indices may differ across tickers.
    method:
        ``"asof"`` (default) — union grid + forward-fill. See module docstring.

    Returns
    -------
    dict[str, pd.DataFrame]
        Each frame reindexed onto the shared union grid (same index for all
        tickers). Grid points before a ticker's first bar are ``NaN``.
    """
    if method not in ALIGNMENT_METHODS:
        raise ValueError(
            f"unknown alignment method {method!r}; expected one of {ALIGNMENT_METHODS}"
        )
    if not bars:
        return {}

    # --- 1. common grid = sorted union of all bar-close timestamps -----------
    index_name = next(iter(bars.values())).index.name or "Date"
    grid = None
    for df in bars.values():
        idx = df.index[~df.index.duplicated(keep="last")]
        grid = idx if grid is None else grid.union(idx)
    grid = pd.DatetimeIndex(grid).sort_values()
    grid.name = index_name

    # --- 2. as-of (forward-fill) reindex each ticker onto the grid -----------
    out: dict[str, pd.DataFrame] = {}
    for ticker, df in bars.items():
        d = df[~df.index.duplicated(keep="last")].sort_index()
        out[ticker] = d.reindex(grid, method="ffill")
    return out
