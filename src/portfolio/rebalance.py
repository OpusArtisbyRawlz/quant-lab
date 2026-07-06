"""
Rebalance-frequency support for cross-sectional strategies.

This module post-processes an already-constructed weight panel so that the
portfolio only changes its weights on rebalance dates and carries those
weights forward in between. It does NOT generate signals or construct
weights — it only controls *how often* the existing weights are refreshed.

With ``rebalance_frequency=1`` the original daily weights are returned
unchanged, so the existing daily-rebalance behaviour is preserved exactly.
"""

import numpy as np
import pandas as pd


def select_rebalance_dates(dates, rebalance_frequency=1) -> pd.Index:
    """
    Select the dates on which the portfolio rebalances.

    Parameters
    ----------
    dates :
        Iterable of dates (the unique trading dates of the panel). Order does
        not matter; the dates are sorted internally.
    rebalance_frequency : int or str, default 1
        ``1`` rebalances every trading day, ``5`` every 5th trading day, etc.
        The string ``"weekly"`` (aliases ``"W"``, ``"week"``) rebalances on the
        first trading day of each ISO calendar week.

    Returns
    -------
    pd.Index
        The subset of dates on which rebalancing occurs, sorted ascending.
    """
    uniq = pd.Index(sorted(pd.unique(dates)))

    if isinstance(rebalance_frequency, str):
        freq = rebalance_frequency.strip().lower()
        if freq in ("w", "week", "weekly"):
            dt = pd.DatetimeIndex(pd.to_datetime(uniq))
            iso = dt.isocalendar()
            week_key = iso["year"].to_numpy() * 100 + iso["week"].to_numpy()
            first_of_week = pd.Series(dt, index=week_key).groupby(level=0).min()
            return pd.Index(sorted(first_of_week.to_numpy()))
        raise ValueError(
            f"Unsupported rebalance_frequency string: {rebalance_frequency!r}"
        )

    n = int(rebalance_frequency)
    if n < 1:
        raise ValueError("rebalance_frequency must be an integer >= 1 or 'weekly'")

    return uniq[::n]


def weights_to_wide(
    panel: pd.DataFrame,
    date_col: str = "Date",
    asset_col: str = "ticker",
    weight_col: str = "weight",
) -> pd.DataFrame:
    """
    Pivot a long-format weight panel into a wide ``Date x asset`` matrix.

    Missing (date, asset) combinations are filled with 0.0, so the result is
    directly consumable by turnover utilities such as
    ``src.analysis.turnover.compute_turnover``.
    """
    wide = panel.pivot_table(
        index=date_col,
        columns=asset_col,
        values=weight_col,
        aggfunc="sum",
    ).sort_index()

    return wide.fillna(0.0)


def apply_rebalance_frequency(
    panel: pd.DataFrame,
    rebalance_frequency=1,
    date_col: str = "Date",
    asset_col: str = "ticker",
    weight_col: str = "weight",
) -> pd.DataFrame:
    """
    Hold weights constant between rebalance dates.

    The input ``panel`` is expected to already contain per-date target weights
    in ``weight_col`` (as produced by the existing pipeline). On each trading
    date, the returned weight is the target weight from the most recent
    rebalance date; weights are carried forward unchanged between rebalances.

    Parameters
    ----------
    panel : pd.DataFrame
        Long-format panel with ``date_col``, ``asset_col`` and ``weight_col``.
    rebalance_frequency : int or str, default 1
        See :func:`select_rebalance_dates`. ``1`` returns the panel unchanged.

    Returns
    -------
    pd.DataFrame
        A copy of ``panel`` with ``weight_col`` replaced by the held weights.
        All other columns (signals, forward returns, etc.) are untouched.
    """
    # Fast path: daily rebalancing is the existing behaviour — leave as-is.
    if rebalance_frequency == 1:
        return panel.copy()

    panel = panel.copy()

    wide = weights_to_wide(
        panel,
        date_col=date_col,
        asset_col=asset_col,
        weight_col=weight_col,
    )

    rebalance_dates = select_rebalance_dates(wide.index, rebalance_frequency)
    is_rebalance = wide.index.isin(rebalance_dates)

    # Blank out non-rebalance rows, then carry the last rebalance book forward.
    held = wide.copy()
    held.loc[~is_rebalance] = np.nan
    held = held.ffill().fillna(0.0)

    held_long = held.reset_index().melt(
        id_vars=date_col,
        var_name=asset_col,
        value_name="_held_weight",
    )

    out = panel.merge(held_long, on=[date_col, asset_col], how="left")
    out[weight_col] = out["_held_weight"].fillna(0.0)
    out = out.drop(columns="_held_weight")

    # Preserve original column order.
    return out[panel.columns]
