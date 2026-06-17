"""
cost_model.py — deterministic turnover, transaction-cost and slippage model.

Milestone 5 adds realistic trading frictions on top of the gross portfolio
return series.  This module is pure: it takes a weighted panel (or a turnover
series) plus a CostConfig and returns per-period cost drags.  No randomness,
no I/O beyond loading the TOML config.

Cost convention
---------------
Costs are charged on **one-way turnover**:

    turnover_t = 0.5 * sum_i | w_{i,t} - w_{i,t-1} |

The first period's turnover is the cost of establishing the book from flat:
0.5 * sum_i |w_{i,0}|.

Per-period return drag:

    transaction_cost_t = turnover_t * (commission_bps + spread_bps) / 1e4
    slippage_t         = turnover_t * slippage_bps / 1e4
    net_ret_t          = gross_ret_t - transaction_cost_t - slippage_t

Import boundary
---------------
Lives inside agents/experiment_runner/ so it may be used alongside the src/
pipeline.  It does not itself import from src/.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

_DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "cost_defaults.toml"


@dataclass(frozen=True)
class CostConfig:
    """
    Transaction-cost assumptions, all in basis points.

    Loaded from agents/config/cost_defaults.toml by default.  Override in
    tests to inject custom costs without touching the checked-in file, or to
    construct a zero-cost config (net == gross) for identity checks.
    """
    commission_bps: float = 1.0
    spread_bps: float = 2.0
    slippage_bps: float = 1.5
    periods_per_year: int = 252

    @property
    def trading_cost_bps(self) -> float:
        """Commission + spread — the non-slippage component of cost."""
        return self.commission_bps + self.spread_bps

    @classmethod
    def zero(cls) -> "CostConfig":
        """A frictionless config: net returns equal gross returns."""
        return cls(commission_bps=0.0, spread_bps=0.0, slippage_bps=0.0)

    @classmethod
    def load(cls, config_path: Path | None = None) -> "CostConfig":
        """
        Read cost assumptions from a TOML file.

        Falls back to the dataclass defaults (with a warning) if the file or a
        TOML parser is unavailable — net metrics degrade gracefully rather than
        aborting an experiment.
        """
        path = config_path or _DEFAULT_CONFIG
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            try:
                import tomli as tomllib  # backport
            except ImportError:
                log.warning(
                    "tomllib/tomli unavailable — using built-in cost defaults."
                )
                return cls()

        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except FileNotFoundError:
            log.warning("cost_defaults.toml not found at %s — using built-in defaults.", path)
            return cls()

        costs = data.get("costs", {})
        annual = data.get("annualisation", {})
        return cls(
            commission_bps=float(costs.get("commission_bps", cls.commission_bps)),
            spread_bps=float(costs.get("spread_bps", cls.spread_bps)),
            slippage_bps=float(costs.get("slippage_bps", cls.slippage_bps)),
            periods_per_year=int(annual.get("periods_per_year", cls.periods_per_year)),
        )


# ---------------------------------------------------------------------------
# Turnover
# ---------------------------------------------------------------------------

def compute_turnover(
    panel: pd.DataFrame,
    *,
    weight_col: str = "weight",
    date_col: str = "Date",
    ticker_col: str = "ticker",
) -> pd.Series:
    """
    Compute one-way per-period turnover from a weighted panel.

    Parameters
    ----------
    panel : DataFrame
        Long panel with at least [date_col, ticker_col, weight_col].
    weight_col, date_col, ticker_col : str
        Column names (defaults match the cross-sectional pipeline output).

    Returns
    -------
    pd.Series
        Indexed by date (sorted), value = 0.5 * sum_i |w_t - w_{t-1}|.
        The first date equals 0.5 * sum_i |w_0| (cost of entering from flat).
        Empty Series if the panel lacks the required columns or rows.
    """
    required = {date_col, ticker_col, weight_col}
    if panel is None or panel.empty or not required.issubset(panel.columns):
        return pd.Series(dtype=float)

    # (date x ticker) weight matrix; missing positions = 0 weight.
    wide = (
        panel.pivot_table(
            index=date_col,
            columns=ticker_col,
            values=weight_col,
            aggfunc="sum",
            fill_value=0.0,
        )
        .sort_index()
    )

    # Previous-period weights; the row before the first is treated as flat (0).
    prev = wide.shift(1).fillna(0.0)
    turnover = 0.5 * (wide - prev).abs().sum(axis=1)
    turnover.name = "turnover"
    return turnover


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------

def transaction_costs(turnover: pd.Series, cfg: CostConfig) -> pd.Series:
    """Per-period commission + spread drag (as a return fraction)."""
    if turnover is None or turnover.empty:
        return pd.Series(dtype=float)
    return turnover * (cfg.trading_cost_bps / 1e4)


def slippage_costs(turnover: pd.Series, cfg: CostConfig) -> pd.Series:
    """Per-period slippage / market-impact drag (as a return fraction)."""
    if turnover is None or turnover.empty:
        return pd.Series(dtype=float)
    return turnover * (cfg.slippage_bps / 1e4)


def apply_costs(
    gross_returns: pd.Series,
    turnover: pd.Series,
    cfg: CostConfig,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Subtract trading frictions from a gross return series.

    Returns
    -------
    (net_returns, tx_cost_series, slippage_series)
        All indexed like ``gross_returns``.  Turnover is aligned to the gross
        index; periods with no turnover information incur zero cost.
    """
    if gross_returns is None or gross_returns.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    aligned_turnover = (
        turnover.reindex(gross_returns.index).fillna(0.0)
        if turnover is not None and not turnover.empty
        else pd.Series(0.0, index=gross_returns.index)
    )

    tx = transaction_costs(aligned_turnover, cfg)
    slip = slippage_costs(aligned_turnover, cfg)
    net = gross_returns - tx - slip
    net.name = "net_return"
    return net, tx, slip
