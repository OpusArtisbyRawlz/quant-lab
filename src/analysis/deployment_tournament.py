"""
deployment_tournament.py — reusable deployment-evaluation battery + tournament.

A general capability (not Project-06-specific): given an evaluated object's return
series and position book, ``evaluate_candidate`` runs the full deployment battery
(performance, drawdown geometry, turnover, transaction-cost stress, capacity,
operational stress) by REUSING the existing ``src/analysis`` and ``src/utils`` modules —
no calculation is re-implemented here. ``rank_field`` computes the evidence-based
DeploymentQuality composite and ordering. ``build_candidate_field`` constructs the
historical Project-06 candidate roster from a supplied deployment base (so the base can
come from the recovered P05 PortfolioSpec rather than a stored CSV).

Ported verbatim from the authoritative tournament driver
(experiments/completed/exp_006_deployment_candidate_tournament/run_tournament.py); the
only change is that the base return/book/exposure are passed in instead of read from
disk, so the tournament runs on the factory-composed deployment base.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.risk.drawdown import (
    compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return,
)
from src.analysis.turnover import compute_turnover
from src.analysis.deployment import transaction_cost_stress, rebalance_analysis
from src.analysis.deployment_stress import capacity_analysis, operational_stress_tests
from src.analysis.liquidity import (
    load_price_volume, daily_dollar_volume, average_daily_volume, capacity_ceiling,
)
from src.analysis.rolling import rolling_metrics
from src.utils.metrics import (
    sharpe_ratio, sortino_ratio, max_drawdown, annualized_return,
    annualized_volatility, ulcer_index, drawdown_stats,
)

# Authoritative constants (run_tournament.py).
TX_COSTS = [0, 2, 5, 10, 20, 50]
REBAL_FREQS = [1, 5, 10, 21]
CAPITAL_LEVELS = [1e4, 5e4, 1e5, 5e5, 1e6, 5e6]
PARTICIPATION_CAP = 0.10
COST_ADJ_BPS = 10.0
PPY = 252
DD_THRESHOLD = 0.05


def vol_multiplier(base_ret: pd.Series, window: int = 252) -> pd.Series:
    rv = base_ret.rolling(window).std() * np.sqrt(PPY)
    m = (rv / rv.mean()) ** 0.5
    return m.clip(0.7, 1.3)


def build_candidate_field(
    base_ret: pd.Series, base_book: pd.DataFrame, v1_ret: pd.Series,
    v1_book: pd.DataFrame, v1_exposure: pd.Series, v2: pd.Series, dates: pd.Index,
) -> list[dict[str, Any]]:
    """The 15-candidate roster (3 groups) built on a supplied deployment base.

    base_ret/base_book: the pre-portfolio-overlay multi-strategy base (Group B source).
    v1_ret/v1_book/v1_exposure: the shipped V1 product (Group A). v2: the historical
    return-only series (Group C). Overlays are the authoritative recipes verbatim.
    """
    dep_dd = compute_drawdown((1 + base_ret).cumprod())
    dep_m = vol_multiplier(base_ret)

    def dep_overlay(e):
        return pd.Series(e, index=dates).fillna(1.0)

    v2_eq = (1 + v2).cumprod()
    v2_dd = compute_drawdown(v2_eq)
    v2_m = vol_multiplier(v2)

    cands: list[dict[str, Any]] = []
    cands.append(dict(
        slug="candidate_v1_baseline", name="Deployment Candidate V1 (baseline)",
        group="A — V1 baseline", source="exp_005_risk_engine_final (as shipped)",
        version="V1", overlay="dual-layer smooth-DD (strategy+portfolio, k5 floor0.55)",
        is_v1=True, has_book=True, ret=v1_ret.copy(), book=v1_book.copy(),
        exposure=v1_exposure.copy()))

    groupB = [
        ("candidate_dd_only", "DD Only (floor0.3,k5)", "smooth DD floor0.3 k5, no vol, no clip",
         dep_overlay(drawdown_exposure_smooth(dep_dd, 0.3, 5))),
        ("candidate_combined", "Combined DD+Vol (floor0.3,k5,clip0.5-1.3)", "(m*smooth(0.3,5)).clip(0.5,1.3)",
         dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.3, 5)).clip(0.5, 1.3))),
        ("candidate_floor03", "Floor 0.3 (m*smooth(0.3,5),clip0.5-1.3)", "floor sweep 0.3",
         dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.3, 5)).clip(0.5, 1.3))),
        ("candidate_floor05", "Floor 0.5 (m*smooth(0.5,5),clip0.5-1.3)", "floor sweep 0.5",
         dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.5, 5)).clip(0.5, 1.3))),
        ("candidate_clip_05_12", "Clip 0.5-1.2 (m*smooth(0.6,5))", "clip sweep 0.5-1.2",
         dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 5)).clip(0.5, 1.2))),
        ("candidate_clip_08_10", "Clip 0.8-1.0 (m*smooth(0.6,5))", "clip sweep 0.8-1.0",
         dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 5)).clip(0.8, 1.0))),
        ("candidate_dd_k1", "DD k=1 (m*smooth(0.6,1),clip0.3-1.5)", "k-sweep k=1",
         dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 1)).clip(0.3, 1.5))),
        ("candidate_dd_k5", "DD k=5 (m*smooth(0.6,5),clip0.3-1.5)", "k-sweep k=5",
         dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 5)).clip(0.3, 1.5))),
    ]
    for sl, nm, ov, e in groupB:
        cands.append(dict(
            slug=sl, name=nm, group="B — deployment-base challenger",
            source="recovered deployment base + overlay", version="-", overlay=ov,
            is_v1=False, has_book=True,
            ret=apply_exposure_to_return(base_ret, e), book=base_book.mul(e, axis=0),
            exposure=e))

    groupC = [
        ("candidate_hist_base", "Historical v2 base (raw, no overlay)", "none",
         pd.Series(1.0, index=dates)),
        ("candidate_hist_dd_only", "Historical DD Only (floor0.3,k5)", "smooth DD floor0.3 k5 (nb cell 20)",
         drawdown_exposure_smooth(v2_dd, 0.3, 5)),
        ("candidate_hist_combined", "Historical Combined (floor0.3,k5,clip0.5-1.3)",
         "(m*smooth(0.3,5)).clip(0.5,1.3) (nb cell 22)", (v2_m * drawdown_exposure_smooth(v2_dd, 0.3, 5)).clip(0.5, 1.3)),
        ("candidate_hist_floor03", "Historical Floor 0.3 (clip0.5-1.3)", "floor sweep 0.3 (nb cell 15)",
         (v2_m * drawdown_exposure_smooth(v2_dd, 0.3, 5)).clip(0.5, 1.3)),
        ("candidate_hist_floor05", "Historical Floor 0.5 (clip0.5-1.3)", "floor sweep 0.5 (nb cell 15)",
         (v2_m * drawdown_exposure_smooth(v2_dd, 0.5, 5)).clip(0.5, 1.3)),
        ("candidate_hist_floor06", "Historical Floor 0.6 (clip0.5-1.3)", "floor sweep 0.6 (nb cell 15)",
         (v2_m * drawdown_exposure_smooth(v2_dd, 0.6, 5)).clip(0.5, 1.3)),
    ]
    for sl, nm, ov, e in groupC:
        e = pd.Series(e, index=dates).fillna(1.0)
        cands.append(dict(
            slug=sl, name=nm, group="C — historical low-MDD challenger",
            source="final_returns_v2_with_dates.csv + overlay (robustness nb)",
            version="-", overlay=ov, is_v1=False, has_book=False,
            ret=apply_exposure_to_return(v2, e), book=None, exposure=e))
    return cands


def evaluate_candidate(cand: dict[str, Any], adv_panel: pd.DataFrame) -> dict[str, Any]:
    """Full deployment battery for one candidate (reuses src/analysis)."""
    ret = pd.Series(cand["ret"]).astype(float)
    exposure = pd.Series(cand["exposure"]).astype(float)
    eq = (1 + ret).cumprod()
    dd = compute_drawdown(eq)
    has_book = cand["has_book"]
    book = cand["book"]
    cagr = annualized_return(ret, PPY)
    mdd = max_drawdown(eq)
    ds = drawdown_stats(eq, threshold=DD_THRESHOLD)
    metrics: dict[str, Any] = {
        "Sharpe": float(sharpe_ratio(ret, PPY)), "Sortino": float(sortino_ratio(ret, PPY)),
        "CAGR": float(cagr), "Volatility": float(annualized_volatility(ret, PPY)),
        "MDD": float(mdd), "Calmar": float(cagr / abs(mdd)) if mdd else np.nan,
        "Ulcer": float(ulcer_index(eq)), "MaxDD_duration_d": ds["max_dd_duration"],
        "MaxDD_recovery_d": ds["max_dd_recovery"], "Longest_underwater_d": ds["longest_underwater"],
        "Time_underwater_frac": ds["time_underwater_frac"], "DD_frequency_gt5pct": ds["frequency"],
        "Avg Exposure": float(exposure.mean()),
    }
    if has_book:
        turnover = compute_turnover(book).reindex(ret.index).fillna(0.0)
        tcs = transaction_cost_stress(ret, turnover, TX_COSTS, periods_per_year=PPY)
        cost_adj = float(tcs.loc[tcs["Cost bps"] == COST_ADJ_BPS, "Sharpe"].iloc[0])
        capacity_analysis(ret, book, CAPITAL_LEVELS, adv=adv_panel, periods_per_year=PPY)
        ceiling = capacity_ceiling(book, adv_panel, participation_cap=PARTICIPATION_CAP)
        ops = operational_stress_tests(ret, book, equity=eq, base_cost_bps=COST_ADJ_BPS,
                                       periods_per_year=PPY)
        metrics.update({
            "Mean Turnover": float(turnover.mean()), "Cost-adj Sharpe (10bps)": cost_adj,
            "Capacity @10% median ($)": float(ceiling["median_capital"]),
            "Capacity @10% p05 ($)": float(ceiling["p05_capital"]),
            "Ops worst Sharpe": float(ops["Sharpe"].min()),
            "Ops Sharpe drop": float(ops["Sharpe"].iloc[0] - ops["Sharpe"].min()),
            "Deployable (has book)": True,
        })
    else:
        metrics.update({
            "Mean Turnover": np.nan, "Cost-adj Sharpe (10bps)": np.nan,
            "Capacity @10% median ($)": np.nan, "Capacity @10% p05 ($)": np.nan,
            "Ops worst Sharpe": np.nan, "Ops Sharpe drop": np.nan,
            "Deployable (has book)": False,
        })
    return metrics


def rank_field(comp: pd.DataFrame) -> pd.DataFrame:
    """Evidence-based DeploymentQuality composite + ordering (verbatim from the driver)."""
    book = comp[comp["Deployable (has book)"]].copy()

    def z(col, frame, invert=False):
        s = frame[col].astype(float)
        sd = s.std(ddof=0)
        zz = (s - s.mean()) / sd if sd > 0 else s * 0.0
        return -zz if invert else zz

    qual = (1.0 * z("Sharpe", book) + 1.0 * z("Sortino", book)
            + 1.0 * z("Cost-adj Sharpe (10bps)", book) + 1.0 * z("Calmar", book)
            + 1.0 * z("MDD", book) + 0.5 * z("Ulcer", book, invert=True)
            + 0.5 * z("Ops worst Sharpe", book))
    comp["DeployQuality"] = np.nan
    comp.loc[book.index, "DeployQuality"] = qual.values

    nobook = comp[~comp["Deployable (has book)"]].copy()
    if len(nobook):
        paper = (z("Sharpe", nobook) + z("Sortino", nobook) + z("Calmar", nobook)
                 + z("MDD", nobook) + 0.5 * z("Ulcer", nobook, invert=True))
        comp.loc[nobook.index, "PaperQuality"] = paper.values

    comp = comp.sort_values(["Deployable (has book)", "DeployQuality", "MDD", "Sharpe"],
                            ascending=[False, False, False, False]).reset_index(drop=True)
    comp.insert(0, "Rank", comp.index + 1)
    return comp


def build_adv_panel(tickers: list[str], dates: pd.Index, data_dir) -> pd.DataFrame:
    """Real ADV panel for the deployment universe (verbatim from the driver)."""
    close, volume = load_price_volume(tickers, data_dir=data_dir)
    adv = average_daily_volume(daily_dollar_volume(close, volume), window=20)
    return adv.reindex(index=dates, columns=tickers).ffill()


def run_tournament(v1_ret, v1_book, v1_exposure, v2, adv_panel):
    """Evaluate the full candidate field and return the ranked master comparison frame.

    ``v1_ret``/``v1_book``/``v1_exposure`` are the shipped V1 product's return, per-ticker
    book, and portfolio-level exposure (from the factory-composed P05 base). The
    pre-portfolio-overlay base is derived exactly as the historical driver does:
    ``base_ret = v1_ret / exposure.shift(1)`` and ``base_book = v1_book / exposure``.
    """
    dates = v1_book.index
    base_ret = v1_ret / v1_exposure.shift(1).fillna(1.0)
    base_book = v1_book.div(v1_exposure, axis=0)
    cands = build_candidate_field(base_ret, base_book, v1_ret, v1_book, v1_exposure, v2, dates)
    rows = []
    for c in cands:
        row = {"Candidate": c["name"], "Group": c["group"], "Source": c["source"],
               "Version": c["version"], "Overlay": c["overlay"], "is_v1": c["is_v1"]}
        row.update(evaluate_candidate(c, adv_panel))
        rows.append(row)
    return rank_field(pd.DataFrame(rows))
