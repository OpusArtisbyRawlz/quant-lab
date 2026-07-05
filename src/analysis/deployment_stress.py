"""
Deployment stress & capacity analytics.

Heavier "is this deployable in production" checks layered on top of the core
deployment battery in :mod:`src.analysis.deployment`. Like the rest of the
deployment analytics these are **pure functions** that operate on an
*already-computed* return series + weight panel — no strategy is reconstructed,
no I/O, no plotting.

A recurring modelling assumption (shared with
:func:`src.analysis.deployment.rebalance_cost_grid`): the *gross* return series
is treated as invariant to execution changes (delays, missed rebalances,
capital scale). Operational frictions are therefore expressed through their
**turnover / transaction-cost** impact, which is what these helpers vary. Each
function documents where that assumption bites and which inputs are genuine
data vs. modelling placeholders.
"""

from typing import Mapping, Sequence, Union

import numpy as np
import pandas as pd

from src.analysis.turnover import compute_turnover
from src.analysis.deployment import transaction_cost_stress
from src.analysis.liquidity import (
    participation_rate,
    slippage_series,
)
from src.risk.drawdown import compute_drawdown
from src.utils.metrics import (
    sharpe_ratio,
    max_drawdown,
    annualized_return,
)


# ---------------------------------------------------------------------------
# 1. Capacity analysis
# ---------------------------------------------------------------------------
def estimate_traded_dollars(
    weights: pd.DataFrame,
    capital: float,
    turnover: pd.Series = None,
) -> pd.Series:
    """
    Per-period one-way traded dollar notional for a given capital base.

    Traded notional = ``capital * one-way turnover``. Turnover is recomputed
    from ``weights`` if not supplied.

    Parameters
    ----------
    weights : pd.DataFrame
        Wide weight matrix indexed by date, columns are assets.
    capital : float
        Deployed capital in dollars.
    turnover : pd.Series, optional
        Precomputed one-way turnover; recomputed from ``weights`` if omitted.

    Returns
    -------
    pd.Series
        Daily traded dollar notional, indexed by date.
    """
    if turnover is None:
        turnover = compute_turnover(weights)
    return capital * turnover


def capacity_analysis(
    returns: pd.Series,
    weights: pd.DataFrame,
    capital_levels: Sequence[float],
    adv: Union[Mapping[str, float], pd.Series, pd.DataFrame, None] = None,
    base_cost_bps: float = 0.0,
    impact_coef: float = 0.1,
    impact_exponent: float = 0.5,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """
    Estimate deployable capacity across a sweep of capital levels.

    For each capital level the per-period one-way *traded dollar notional* is
    estimated from the weight path (``capital * turnover``), and a net
    performance figure is produced.

    Market-impact / liquidity model
    -------------------------------
    The impact chain is delegated wholesale to :mod:`src.analysis.liquidity`
    (single source of truth): traded$ -> participation = traded$ / ADV ->
    power-law impact -> per-day slippage drag. ``adv`` carries real per-asset
    average daily dollar volume:

    * ``adv`` provided — a ``ticker -> ADV $`` mapping/Series (broadcast across
      dates) or a per-date ``date x ticker`` DataFrame (e.g. from
      :func:`src.analysis.liquidity.average_daily_volume`). Per asset,
      participation = traded$ / ADV and the square-root law charges
      ``impact_coef * participation ** impact_exponent`` (default
      ``impact_exponent=0.5``) on that asset's traded fraction; the per-day
      slippage is the asset sum. Net performance therefore degrades as capital
      rises.
    * ``adv=None`` — **no-impact placeholder.** Net performance is identical
      across capital levels (``ADV Provided == False``, ``Mean Impact bps == 0``);
      only the traded-dollar columns vary. Use it to read the *scale* of trading
      implied, not a hard capacity ceiling.

    Parameters
    ----------
    returns : pd.Series
        Daily gross (pre-cost) portfolio return series.
    weights : pd.DataFrame
        Wide weight matrix indexed by date, columns are assets.
    capital_levels : sequence of float
        Capital bases in dollars, e.g. ``[1e4, 5e4, 1e5, 5e5, 1e6, 5e6]``.
    adv : mapping / Series / DataFrame, optional
        Average daily dollar volume per asset. See model note above.
    base_cost_bps : float, default 0.0
        Flat one-way cost (bps) charged on turnover at every capital level,
        on top of any modelled impact.
    impact_coef, impact_exponent : float
        Power-law market-impact parameters (only used when ``adv`` is given).
    periods_per_year : int, default 252
        Annualisation factor.

    Returns
    -------
    pd.DataFrame
        One row per capital level with columns ``Capital``, ``ADV Provided``,
        ``Mean Daily Traded $``, ``Max Daily Traded $``, ``Annual Traded $``,
        ``Mean Participation``, ``Mean Impact bps``, ``Sharpe``, ``CAGR`` and
        ``MDD``.
    """
    returns = pd.Series(returns).astype(float)
    weights = weights.sort_index()
    turnover = compute_turnover(weights).reindex(returns.index).fillna(0.0)

    adv_provided = adv is not None

    # Build a date x ticker ADV panel for the liquidity chain. A mapping/Series
    # of per-ticker ADV is broadcast across all dates; a DataFrame is used as-is.
    adv_panel = None
    if adv_provided:
        if isinstance(adv, pd.DataFrame):
            adv_panel = adv
        else:
            adv_series = pd.Series(adv, dtype=float).reindex(weights.columns)
            adv_panel = pd.DataFrame(
                np.tile(adv_series.to_numpy(), (len(weights.index), 1)),
                index=weights.index,
                columns=weights.columns,
            )

    base_cost_drag = turnover * (base_cost_bps / 10000.0)

    rows = []
    for capital in capital_levels:
        traded = capital * turnover  # one-way portfolio traded $ per day

        mean_participation = np.nan
        mean_impact_bps = 0.0
        impact_drag = pd.Series(0.0, index=returns.index)

        if adv_provided:
            # Delegate the impact chain to src.analysis.liquidity (single source
            # of truth): participation -> square-root impact -> slippage drag.
            participation = participation_rate(weights, capital, adv_panel)
            slippage = slippage_series(
                weights, participation, coef=impact_coef, exponent=impact_exponent
            )
            impact_drag = slippage.reindex(returns.index).fillna(0.0)
            mean_participation = float(np.nanmean(participation.to_numpy()))
            mean_impact_bps = float(impact_drag.mean() * 10000.0)

        net = returns - base_cost_drag - impact_drag
        equity = (1 + net).cumprod()

        rows.append(
            {
                "Capital": capital,
                "ADV Provided": adv_provided,
                "Mean Daily Traded $": float(traded.mean()),
                "Max Daily Traded $": float(traded.max()),
                "Annual Traded $": float(traded.mean() * periods_per_year),
                "Mean Participation": mean_participation,
                "Mean Impact bps": mean_impact_bps,
                "Sharpe": sharpe_ratio(net, periods_per_year),
                "CAGR": annualized_return(net, periods_per_year),
                "MDD": max_drawdown(equity),
            }
        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Rolling transaction-cost drag
# ---------------------------------------------------------------------------
def transaction_cost_drag(
    returns: pd.Series,
    turnover: pd.Series,
    transaction_costs: Sequence[float],
    periods_per_year: int = 252,
) -> dict:
    """
    Cumulative transaction-cost drag through time for a sweep of cost levels.

    For each cost level the per-period cost is ``turnover * cost_bps / 1e4`` and
    the net return is ``returns - cost``. Reuses
    :func:`src.analysis.deployment.transaction_cost_stress` for the final
    per-cost summary so the headline metrics match the rest of the report.

    Parameters
    ----------
    returns : pd.Series
        Daily gross (pre-cost) portfolio return series.
    turnover : pd.Series
        Daily one-way turnover; reindexed to ``returns`` and zero-filled.
    transaction_costs : sequence of float
        One-way costs in basis points (e.g. ``[0, 2, 5, 10, 20, 50]``).
    periods_per_year : int, default 252
        Annualisation factor.

    Returns
    -------
    dict
        ``{
            "net_equity":      pd.DataFrame,  # date x cost, growth-of-1 net
            "cumulative_drag": pd.DataFrame,  # date x cost, gross_eq - net_eq
            "summary":         pd.DataFrame,  # per-cost Sharpe/MDD/CAGR/Calmar
        }``
    """
    returns = pd.Series(returns).astype(float)
    aligned = pd.Series(turnover).reindex(returns.index).fillna(0.0)

    gross_equity = (1 + returns).cumprod()

    net_eq_cols, drag_cols = {}, {}
    for cost_bps in transaction_costs:
        net = returns - aligned * (cost_bps / 10000.0)
        eq = (1 + net).cumprod()
        net_eq_cols[cost_bps] = eq
        drag_cols[cost_bps] = gross_equity - eq

    net_equity = pd.DataFrame(net_eq_cols, index=returns.index)
    cumulative_drag = pd.DataFrame(drag_cols, index=returns.index)
    net_equity.columns.name = "Cost bps"
    cumulative_drag.columns.name = "Cost bps"

    summary = transaction_cost_stress(
        returns, aligned, transaction_costs, periods_per_year=periods_per_year
    )

    return {
        "net_equity": net_equity,
        "cumulative_drag": cumulative_drag,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 3. Operational stress tests
# ---------------------------------------------------------------------------
def skip_every_nth_rebalance(weights: pd.DataFrame, n: int) -> pd.DataFrame:
    """
    Simulate missed rebalances by skipping every ``n``-th trade.

    On the trading days where the strategy would normally refresh its book
    (one-way turnover > 0), every ``n``-th such day is forced to carry the
    previous weights forward instead of trading. The result is a new wide
    weight matrix with reduced (and re-timed) turnover.

    Parameters
    ----------
    weights : pd.DataFrame
        Wide weight matrix indexed by date, columns are assets.
    n : int
        Skip cadence; ``n=4`` drops every 4th rebalance.

    Returns
    -------
    pd.DataFrame
        Weight matrix with the skipped rebalances carried forward.
    """
    if n < 1:
        raise ValueError("n must be a positive integer")

    wide = weights.sort_index().copy()
    turnover = compute_turnover(wide)
    trade_days = list(turnover.index[turnover > 0])
    skipped = set(trade_days[n - 1 :: n])  # the n-th, 2n-th, ... trade days

    held = wide.copy()
    held.loc[held.index.isin(skipped)] = np.nan
    held = held.ffill().fillna(0.0)
    return held


def _scenario_metrics(
    returns: pd.Series,
    turnover: pd.Series,
    cost_rate,
    scenario: str,
    periods_per_year: int = 252,
) -> dict:
    """One row of net performance for an operational scenario.

    ``cost_rate`` is a decimal one-way rate (scalar or per-date Series) applied
    to ``turnover``. Gross ``returns`` are held fixed (see module docstring).
    """
    turnover = pd.Series(turnover).reindex(returns.index).fillna(0.0)
    if np.isscalar(cost_rate):
        cost = turnover * float(cost_rate)
    else:
        cost = turnover * pd.Series(cost_rate).reindex(returns.index).fillna(0.0)

    net = returns - cost
    equity = (1 + net).cumprod()
    return {
        "Scenario": scenario,
        "Sharpe": sharpe_ratio(net, periods_per_year),
        "CAGR": annualized_return(net, periods_per_year),
        "MDD": max_drawdown(equity),
        "Mean Turnover": float(turnover.mean()),
        "Total Cost Drag": float(cost.sum()),
    }


def operational_stress_tests(
    returns: pd.Series,
    weights: pd.DataFrame,
    equity: pd.Series = None,
    base_cost_bps: float = 10.0,
    missed_rebalance_n: int = 4,
    execution_delay_days: int = 1,
    vol_window: int = 20,
    vol_quantile: float = 0.90,
    highvol_cost_multiplier: float = 2.0,
    dd_worst_quantile: float = 0.10,
    liquidity_shock_multipliers: Sequence[float] = (2.0, 3.0),
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """
    Run a battery of operational / execution stress scenarios.

    All scenarios share the deployment approximation that the *gross* return
    series is invariant to execution changes; frictions are expressed through
    turnover and transaction cost (see module docstring). Each scenario is
    charged a base one-way cost of ``base_cost_bps`` except where a multiplier
    is applied.

    Scenarios
    ---------
    * **Baseline** — as-deployed weights at ``base_cost_bps``.
    * **Missed rebalance (every Nth)** — :func:`skip_every_nth_rebalance` with
      ``missed_rebalance_n``; reduced, re-timed turnover.
    * **Execution delay (D days)** — weights shifted forward
      ``execution_delay_days`` (yesterday's book traded today); isolates the
      turnover/timing cost effect (gross-return impact is not estimable from
      portfolio-level data alone).
    * **Doubled cost in high-vol periods** — days whose trailing
      ``vol_window`` realised vol exceeds the ``vol_quantile`` cut are charged
      ``highvol_cost_multiplier x`` base cost.
    * **Liquidity shock during worst drawdowns** — for each multiplier in
      ``liquidity_shock_multipliers``, the worst ``dd_worst_quantile`` fraction
      of drawdown days are charged that multiple of base cost.

    Returns
    -------
    pd.DataFrame
        One row per scenario with columns ``Scenario``, ``Sharpe``, ``CAGR``,
        ``MDD``, ``Mean Turnover`` and ``Total Cost Drag``.
    """
    returns = pd.Series(returns).astype(float)
    weights = weights.sort_index()
    base_rate = base_cost_bps / 10000.0

    turnover = compute_turnover(weights).reindex(returns.index).fillna(0.0)

    if equity is None:
        equity = (1 + returns.fillna(0)).cumprod()
    equity = pd.Series(equity).astype(float).reindex(returns.index)

    rows = []

    # Baseline ---------------------------------------------------------------
    rows.append(
        _scenario_metrics(
            returns, turnover, base_rate, "Baseline", periods_per_year
        )
    )

    # Missed rebalance -------------------------------------------------------
    missed_weights = skip_every_nth_rebalance(weights, missed_rebalance_n)
    missed_turnover = compute_turnover(missed_weights)
    rows.append(
        _scenario_metrics(
            returns,
            missed_turnover,
            base_rate,
            f"Missed rebalance (every {missed_rebalance_n}th)",
            periods_per_year,
        )
    )

    # Execution delay --------------------------------------------------------
    delayed_weights = weights.shift(execution_delay_days).fillna(0.0)
    delayed_turnover = compute_turnover(delayed_weights)
    rows.append(
        _scenario_metrics(
            returns,
            delayed_turnover,
            base_rate,
            f"Execution delay ({execution_delay_days}d)",
            periods_per_year,
        )
    )

    # Doubled cost in high-vol periods --------------------------------------
    roll_vol = returns.rolling(vol_window).std()
    vol_cut = roll_vol.quantile(vol_quantile)
    highvol_mask = (roll_vol >= vol_cut).fillna(False)
    highvol_rate = pd.Series(base_rate, index=returns.index)
    highvol_rate[highvol_mask] = base_rate * highvol_cost_multiplier
    rows.append(
        _scenario_metrics(
            returns,
            turnover,
            highvol_rate,
            f"High-vol {highvol_cost_multiplier:g}x cost",
            periods_per_year,
        )
    )

    # Liquidity shock during worst drawdowns --------------------------------
    drawdown = compute_drawdown(equity)
    dd_cut = drawdown.quantile(dd_worst_quantile)  # most-negative tail
    shock_mask = (drawdown <= dd_cut).fillna(False)
    for mult in liquidity_shock_multipliers:
        shock_rate = pd.Series(base_rate, index=returns.index)
        shock_rate[shock_mask] = base_rate * mult
        rows.append(
            _scenario_metrics(
                returns,
                turnover,
                shock_rate,
                f"Liquidity shock {mult:g}x (worst DD)",
                periods_per_year,
            )
        )

    return pd.DataFrame(rows)
