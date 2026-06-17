"""
robustness.py — deterministic robustness checks for Milestone 5.

Produces a small, auditable robustness report alongside the net metrics:

  * subperiod_sharpes      — net Sharpe in each contiguous subperiod
  * parameter_sensitivity  — net Sharpe across a small grid of long/short
                             quantile perturbations (fragility, not tuning)
  * robustness_flags       — list of triggered warnings, drawn from:
        - "subperiod_instability"
        - "parameter_fragility"
        - "cost_fragility"

M5 does NOT implement formal overfitting statistics (deflated Sharpe, PBO).
These flags are heuristic deployability warnings, consistent with the rolling
performance judgement used in Project 04.  Formal statistics and the rolling
robustness suite are tracked on the roadmap for a later milestone.

Parameter sensitivity uses a one-at-a-time grid (vary long_quantile while
short is held, then vary short_quantile while long is held).  The goal is to
detect whether the strategy survives small parameter changes — it is a
fragility probe, never an optimiser.
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import pandas as pd

from agents.experiment_runner.metrics_writer import compute_metrics
from agents.experiment_runner.cost_model import CostConfig, compute_turnover, apply_costs

# src/ import — permitted inside experiment_runner
from src.signals.combine import apply_signal_combo

log = logging.getLogger(__name__)

FLAG_SUBPERIOD = "subperiod_instability"
FLAG_PARAMETER = "parameter_fragility"
FLAG_COST = "cost_fragility"


# ---------------------------------------------------------------------------
# Subperiod analysis
# ---------------------------------------------------------------------------

def subperiod_sharpes(
    returns: pd.Series,
    n_splits: int = 3,
    periods_per_year: int = 252,
) -> list[float | None]:
    """
    Split a return series into ``n_splits`` contiguous chunks and return the
    Sharpe of each.  Used to detect performance that is concentrated in one
    regime rather than persistent.
    """
    r = returns.dropna()
    if len(r) < n_splits or n_splits < 1:
        return []
    chunks = np.array_split(r.to_numpy(), n_splits)
    out: list[float | None] = []
    for chunk in chunks:
        m = compute_metrics(pd.Series(chunk), periods_per_year)
        out.append(m.get("sharpe"))
    return out


# ---------------------------------------------------------------------------
# Parameter sensitivity
# ---------------------------------------------------------------------------

def parameter_sensitivity(
    base_panel: pd.DataFrame,
    signal_names: list[str],
    portfolio_return_fn: Callable[[pd.DataFrame], pd.Series],
    cfg: CostConfig,
    *,
    base_long: float = 0.8,
    base_short: float = 0.2,
    delta: float = 0.05,
    periods_per_year: int = 252,
) -> dict:
    """
    Probe net-Sharpe stability under small long/short quantile perturbations.

    Grid (one-at-a-time around the base configuration):
        long_quantile  in {base_long - delta, base_long, base_long + delta}
        short_quantile in {base_short - delta, base_short, base_short + delta}

    Parameters
    ----------
    base_panel : DataFrame
        Panel with signals/features already built (pre signal-combo).
    signal_names : list[str]
        Signals to combine.
    portfolio_return_fn : callable
        Maps a weighted panel → daily gross return Series.  Supplied by the
        runner so the forward-return column name lives in one place.
    cfg : CostConfig
        Cost assumptions, so sensitivity is measured on NET Sharpe.

    Returns
    -------
    dict
        {
          "points": [{"long": l, "short": s, "net_sharpe": x}, ...],
          "net_sharpe_min": ..., "net_sharpe_max": ..., "net_sharpe_spread": ...,
        }
    """
    grid: list[tuple[float, float]] = [(base_long, base_short)]
    for d in (-delta, delta):
        grid.append((round(base_long + d, 4), base_short))
        grid.append((base_long, round(base_short + d, 4)))

    points: list[dict] = []
    for lq, sq in grid:
        # Guard against degenerate quantiles.
        if not (0.0 < sq < lq < 1.0):
            continue
        try:
            panel = apply_signal_combo(
                base_panel, signal_names, long_quantile=lq, short_quantile=sq
            )
            gross = portfolio_return_fn(panel)
            turnover = compute_turnover(panel)
            net, _, _ = apply_costs(gross, turnover, cfg)
            net_sharpe = compute_metrics(net, periods_per_year).get("sharpe")
        except Exception:
            log.exception("parameter_sensitivity grid point (%.2f, %.2f) failed", lq, sq)
            net_sharpe = None
        points.append({"long": lq, "short": sq, "net_sharpe": net_sharpe})

    valid = [p["net_sharpe"] for p in points if p["net_sharpe"] is not None]
    if valid:
        smin, smax = min(valid), max(valid)
        spread = round(smax - smin, 6)
    else:
        smin = smax = spread = None

    return {
        "points": points,
        "net_sharpe_min": smin,
        "net_sharpe_max": smax,
        "net_sharpe_spread": spread,
    }


# ---------------------------------------------------------------------------
# Report assembly + flagging
# ---------------------------------------------------------------------------

def build_robustness_report(
    *,
    net_returns: pd.Series,
    gross_sharpe: float | None,
    net_sharpe: float | None,
    sensitivity: dict | None,
    n_splits: int = 3,
    periods_per_year: int = 252,
    spread_tolerance: float = 0.75,
    cost_retain_min: float = 0.5,
) -> dict:
    """
    Assemble the robustness report and compute robustness_flags.

    Flag logic
    ----------
    subperiod_instability : any subperiod net Sharpe is None or < 0, OR the
        subperiod Sharpes are sign-inconsistent (mix of >0 and <0).
    parameter_fragility   : sensitivity spread exceeds ``spread_tolerance``,
        OR any grid point flips sign relative to the base net Sharpe.
    cost_fragility        : gross Sharpe is positive but net Sharpe is None,
        <= 0, or retains less than ``cost_retain_min`` of the gross Sharpe.

    Returns
    -------
    dict with keys: subperiod_sharpes, parameter_sensitivity, robustness_flags.
    """
    sub = subperiod_sharpes(net_returns, n_splits=n_splits, periods_per_year=periods_per_year)
    flags: list[str] = []

    # ── Subperiod instability ─────────────────────────────────────────────
    if sub:
        signs = [s for s in sub if s is not None]
        any_missing = any(s is None for s in sub)
        any_negative = any((s is not None and s < 0) for s in sub)
        mixed_sign = (any(s > 0 for s in signs) and any(s < 0 for s in signs)) if signs else False
        if any_missing or any_negative or mixed_sign:
            flags.append(FLAG_SUBPERIOD)

    # ── Parameter fragility ───────────────────────────────────────────────
    if sensitivity:
        spread = sensitivity.get("net_sharpe_spread")
        if spread is not None and spread > spread_tolerance:
            flags.append(FLAG_PARAMETER)
        elif net_sharpe is not None:
            base_sign = np.sign(net_sharpe)
            for p in sensitivity.get("points", []):
                ns = p.get("net_sharpe")
                if ns is not None and base_sign != 0 and np.sign(ns) != base_sign:
                    flags.append(FLAG_PARAMETER)
                    break

    # ── Cost fragility ────────────────────────────────────────────────────
    if gross_sharpe is not None and gross_sharpe > 0:
        if net_sharpe is None or net_sharpe <= 0 or net_sharpe < cost_retain_min * gross_sharpe:
            flags.append(FLAG_COST)

    # De-duplicate while preserving order.
    seen: set[str] = set()
    ordered_flags = [f for f in flags if not (f in seen or seen.add(f))]

    return {
        "subperiod_sharpes": sub,
        "parameter_sensitivity": sensitivity or {},
        "robustness_flags": ordered_flags,
    }
