"""
exp_006 — Deployment Overlay Challenge
======================================

Controlled experiment: does any drawdown/risk overlay discovered in
``research/project_06_deployment_validation/notebooks/05_robustness_checks.ipynb``
beat the *current* US deployment candidate when run through the **exact same**
deployment-validation battery?

ONE independent variable: the portfolio-level risk overlay. Everything else
(base portfolio, weights, return series, dates, universe, rebalance logic,
transaction-cost model, capacity model, operational-stress framework) is held
identical to the shipped deployment candidate.

Base (incumbent) = exp_005 dual-layer smooth-DD product:
    experiments/completed/exp_005_risk_engine_final/
        final_weighted_multi_strategy_portfolio_dd.csv   (portfolio_return, equity_curve, portfolio_dd_exposure)
        final_daily_weights.csv                          (Date, Ticker, Weight)

The portfolio-level overlay is the OUTERMOST scalar on both the return and the
book (book gross |w| correlates 0.98 with the stored exposure). We strip it to
recover the shared base, then re-apply each challenger overlay:

    base_return_t = portfolio_return_t / exposure_{t-1}      (lagged, look-ahead-safe)
    base_book_t   = final_weight_t    / exposure_t           (contemporaneous book scaling)

    candidate_return_t  = base_return_t * e_cand_{t-1}
    candidate_book_t    = base_book_t   * e_cand_t

Outputs (written next to this script):
    overlay_comparison.csv          ranked master comparison table
    overlay_equity_curves.csv       date x candidate growth-of-1
    overlay_drawdowns.csv           date x candidate drawdown
    overlay_exposures.csv           date x candidate overlay exposure
    txcost_stress_<slug>.csv        per-candidate transaction-cost stress
    rebalance_analysis_<slug>.csv   per-candidate rebalance turnover table
    capacity_<slug>.csv             per-candidate capacity sweep
    operational_stress_<slug>.csv   per-candidate operational stress battery
    rolling_metrics_<slug>.csv      per-candidate rolling 252d metrics
"""

import os
import re
import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.append(str(PROJECT_ROOT))

from src.risk.drawdown import (
    compute_drawdown,
    drawdown_exposure_smooth,
    apply_exposure_to_return,
)
from src.analysis.turnover import compute_turnover
from src.analysis.deployment import transaction_cost_stress, rebalance_analysis
from src.analysis.deployment_stress import (
    capacity_analysis,
    operational_stress_tests,
)
from src.analysis.liquidity import (
    load_price_volume,
    daily_dollar_volume,
    average_daily_volume,
    capacity_ceiling,
)
from src.analysis.rolling import rolling_metrics
from src.utils.metrics import (
    sharpe_ratio,
    max_drawdown,
    annualized_return,
    annualized_volatility,
)

HERE = Path(__file__).resolve().parent
EXP5 = PROJECT_ROOT / "experiments/completed/exp_005_risk_engine_final"

TX_COSTS = [0, 2, 5, 10, 20, 50]
REBAL_FREQS = [1, 5, 10, 21]
CAPITAL_LEVELS = [1e4, 5e4, 1e5, 5e5, 1e6, 5e6]
PARTICIPATION_CAP = 0.10
COST_ADJ_BPS = 10.0
PPY = 252


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ---------------------------------------------------------------------------
# 1. Load deployment base and recover the shared (pre-portfolio-overlay) base
# ---------------------------------------------------------------------------
def load_base():
    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    wide = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index()

    assert len(dep) == len(wide), f"row mismatch dep={len(dep)} weights={len(wide)}"
    dates = wide.index
    dep.index = dates

    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)
    exp_lag = exp.shift(1).fillna(1.0)

    # recover shared base (strip ONLY the portfolio-level overlay)
    base_ret = pr / exp_lag                       # lagged application
    base_book = wide.div(exp, axis=0)             # contemporaneous book scaling

    # incumbent (as shipped) — exact
    incumbent = {
        "name": "Deployment (incumbent, as shipped)",
        "exposure": exp,
        "ret": pr,
        "book": wide,
        "is_incumbent": True,
    }
    return base_ret, base_book, incumbent, dates


# ---------------------------------------------------------------------------
# 2. Overlay definitions (faithful to 05_robustness_checks.ipynb)
#    Each returns a contemporaneous exposure series e_t on the base equity.
# ---------------------------------------------------------------------------
def vol_multiplier(base_ret, window=252):
    rv = base_ret.rolling(window).std() * np.sqrt(PPY)
    m = (rv / rv.mean()) ** 0.5
    return m.clip(0.7, 1.3)


def build_overlays(base_ret):
    base_eq = (1 + base_ret).cumprod()
    dd = compute_drawdown(base_eq)
    m = vol_multiplier(base_ret)

    def smooth(floor, k):
        return drawdown_exposure_smooth(dd, floor=floor, k=k)

    overlays = []

    # Reference / consistency: incumbent recipe recomputed on the base
    overlays.append(("Smooth DD (k5, floor0.55) [config recipe]",
                     smooth(0.55, 5)))

    # 1. DD Only (cell 20): smooth DD floor0.3 k5, no vol, no extra clip
    overlays.append(("DD Only (floor0.3, k5)", smooth(0.3, 5)))

    # 2. Combined DD+Vol (cell 22): (m * smooth(0.3,5)).clip(0.5,1.3)
    overlays.append(("Combined DD+Vol (floor0.3, k5, clip0.5-1.3)",
                     (m * smooth(0.3, 5)).clip(0.5, 1.3)))

    # 3. Floor 0.3 (cell 15 floor sweep) == Combined above (identical recipe)
    overlays.append(("Floor 0.3 (m*smooth(0.3,5), clip0.5-1.3)",
                     (m * smooth(0.3, 5)).clip(0.5, 1.3)))

    # 4. Floor 0.5 (cell 15 floor sweep)
    overlays.append(("Floor 0.5 (m*smooth(0.5,5), clip0.5-1.3)",
                     (m * smooth(0.5, 5)).clip(0.5, 1.3)))

    # 5. Clip 0.5-1.2 (cell 9 clip sweep, floor0.6 k5)
    overlays.append(("Clip 0.5-1.2 (m*smooth(0.6,5))",
                     (m * smooth(0.6, 5)).clip(0.5, 1.2)))

    # 6. Clip 0.8-1.0 (cell 9 clip sweep, floor0.6 k5)
    overlays.append(("Clip 0.8-1.0 (m*smooth(0.6,5))",
                     (m * smooth(0.6, 5)).clip(0.8, 1.0)))

    # 7. k=1 (cell 5 k-sweep, floor0.6, clip0.3-1.5)
    overlays.append(("DD k=1 (m*smooth(0.6,1), clip0.3-1.5)",
                     (m * smooth(0.6, 1)).clip(0.3, 1.5)))

    # 8. k=5 (cell 5 k-sweep, floor0.6, clip0.3-1.5)
    overlays.append(("DD k=5 (m*smooth(0.6,5), clip0.3-1.5)",
                     (m * smooth(0.6, 5)).clip(0.3, 1.5)))

    out = []
    for name, e in overlays:
        e = pd.Series(e, index=base_ret.index).fillna(1.0)
        out.append({"name": name, "exposure": e, "is_incumbent": False})
    return out


# ---------------------------------------------------------------------------
# 3. Apply an overlay to the base -> candidate return + book
# ---------------------------------------------------------------------------
def materialize(cand, base_ret, base_book):
    if cand.get("ret") is not None:
        return cand  # incumbent already materialized
    e = cand["exposure"]
    cand["ret"] = apply_exposure_to_return(base_ret, e)      # lagged
    cand["book"] = base_book.mul(e, axis=0)                  # contemporaneous
    return cand


# ---------------------------------------------------------------------------
# 4. Full validation battery on one candidate
# ---------------------------------------------------------------------------
def validate(cand, adv_panel):
    name = cand["name"]
    ret = pd.Series(cand["ret"]).astype(float)
    book = cand["book"]
    exposure = pd.Series(cand["exposure"]).astype(float)
    eq = (1 + ret).cumprod()
    dd = compute_drawdown(eq)
    turnover = compute_turnover(book).reindex(ret.index).fillna(0.0)

    # headline
    sharpe = sharpe_ratio(ret, PPY)
    cagr = annualized_return(ret, PPY)
    mdd = max_drawdown(eq)
    vol = annualized_volatility(ret, PPY)
    calmar = cagr / abs(mdd) if mdd and mdd == mdd else np.nan

    # transaction-cost stress
    tcs = transaction_cost_stress(ret, turnover, TX_COSTS, periods_per_year=PPY)
    cost_adj_sharpe = float(tcs.loc[tcs["Cost bps"] == COST_ADJ_BPS, "Sharpe"].iloc[0])

    # rebalance analysis
    reb = rebalance_analysis(book, REBAL_FREQS)

    # capacity sweep + ceiling
    cap = capacity_analysis(ret, book, CAPITAL_LEVELS, adv=adv_panel,
                            periods_per_year=PPY)
    ceiling = capacity_ceiling(book, adv_panel, participation_cap=PARTICIPATION_CAP)

    # operational stress
    ops = operational_stress_tests(ret, book, equity=eq,
                                   base_cost_bps=COST_ADJ_BPS,
                                   periods_per_year=PPY)
    ops_worst_sharpe = float(ops["Sharpe"].min())
    ops_worst_mdd = float(ops["MDD"].min())
    ops_sharpe_drop = float(ops["Sharpe"].iloc[0] - ops["Sharpe"].min())

    # rolling metrics
    roll = rolling_metrics(ret, window=PPY, periods_per_year=PPY)

    summary = {
        "Strategy": "US multi-strategy (P05 base)",
        "Overlay": name,
        "Sharpe": sharpe,
        "CAGR": cagr,
        "MDD": mdd,
        "Calmar": calmar,
        "Volatility": vol,
        "Avg Exposure": float(exposure.mean()),
        "Mean Turnover": float(turnover.mean()),
        "Capacity @10% (median $)": ceiling["median_capital"],
        "Capacity @10% (p05 $)": ceiling["p05_capital"],
        "Cost-adj Sharpe (10bps)": cost_adj_sharpe,
        "Ops worst Sharpe": ops_worst_sharpe,
        "Ops worst MDD": ops_worst_mdd,
        "Ops Sharpe drop": ops_sharpe_drop,
        "is_incumbent": cand.get("is_incumbent", False),
    }

    artifacts = {
        "equity": eq, "drawdown": dd, "exposure": exposure,
        "txcost": tcs, "rebalance": reb, "capacity": cap,
        "operational": ops, "rolling": roll,
    }
    return summary, artifacts


# ---------------------------------------------------------------------------
# 5. Orchestrate
# ---------------------------------------------------------------------------
def main():
    base_ret, base_book, incumbent, dates = load_base()

    # ADV panel (real per-asset average daily dollar volume)
    tickers = list(base_book.columns)
    close, volume = load_price_volume(tickers,
                                      data_dir=PROJECT_ROOT / "data/raw/project_04_universe")
    adv = average_daily_volume(daily_dollar_volume(close, volume), window=20)
    adv_panel = adv.reindex(index=dates, columns=tickers).ffill()

    candidates = [incumbent] + build_overlays(base_ret)
    # add the explicit "no overlay" base for context
    candidates.append({
        "name": "Base (no portfolio overlay)",
        "exposure": pd.Series(1.0, index=base_ret.index),
        "ret": base_ret,
        "book": base_book,
        "is_incumbent": False,
    })

    rows = []
    eq_cols, dd_cols, exp_cols = {}, {}, {}
    for cand in candidates:
        cand = materialize(cand, base_ret, base_book)
        summary, art = validate(cand, adv_panel)
        rows.append(summary)
        col = summary["Overlay"]
        eq_cols[col] = art["equity"]
        dd_cols[col] = art["drawdown"]
        exp_cols[col] = art["exposure"]
        s = slug(col)
        art["txcost"].to_csv(HERE / f"txcost_stress_{s}.csv", index=False)
        art["rebalance"].to_csv(HERE / f"rebalance_analysis_{s}.csv", index=False)
        art["capacity"].to_csv(HERE / f"capacity_{s}.csv", index=False)
        art["operational"].to_csv(HERE / f"operational_stress_{s}.csv", index=False)
        art["rolling"].to_csv(HERE / f"rolling_metrics_{s}.csv")

    comp = pd.DataFrame(rows)

    # ----- Ranking -----
    # Deployment-quality composite (higher = better), all robustness-aware:
    #   reward Sharpe, Calmar, cost-adjusted Sharpe, operational resilience;
    #   reward shallower MDD; penalize cost/ops Sharpe erosion.
    def z(s, invert=False):
        s = comp[s].astype(float)
        sd = s.std(ddof=0)
        zz = (s - s.mean()) / sd if sd > 0 else s * 0.0
        return -zz if invert else zz

    comp["DeployQuality"] = (
        1.0 * z("Sharpe")
        + 1.0 * z("Cost-adj Sharpe (10bps)")
        + 1.0 * z("Calmar")
        + 1.0 * z("MDD")                 # less negative -> higher z -> better
        + 0.5 * z("Ops worst Sharpe")
        - 0.5 * z("Ops Sharpe drop")
    )

    comp = comp.sort_values(
        ["DeployQuality", "MDD", "Sharpe", "Calmar"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    comp.insert(0, "Rank", comp.index + 1)

    comp.to_csv(HERE / "overlay_comparison.csv", index=False)
    pd.DataFrame(eq_cols).to_csv(HERE / "overlay_equity_curves.csv")
    pd.DataFrame(dd_cols).to_csv(HERE / "overlay_drawdowns.csv")
    pd.DataFrame(exp_cols).to_csv(HERE / "overlay_exposures.csv")

    # config / provenance
    config = {
        "experiment": "exp_006_deployment_overlay_challenge",
        "base_files": [
            "exp_005_risk_engine_final/final_weighted_multi_strategy_portfolio_dd.csv",
            "exp_005_risk_engine_final/final_daily_weights.csv",
        ],
        "base_recovery": {
            "base_return": "portfolio_return_t / exposure_{t-1} (lagged)",
            "base_book": "final_weight_t / exposure_t (contemporaneous)",
        },
        "n_days": int(len(dates)),
        "date_range": [str(dates[0].date()), str(dates[-1].date())],
        "universe": tickers,
        "tx_costs_bps": TX_COSTS,
        "rebalance_freqs": REBAL_FREQS,
        "capital_levels": CAPITAL_LEVELS,
        "participation_cap": PARTICIPATION_CAP,
        "cost_adj_bps": COST_ADJ_BPS,
        "incumbent_metrics": {
            "Sharpe": float(rows[0]["Sharpe"]),
            "CAGR": float(rows[0]["CAGR"]),
            "MDD": float(rows[0]["MDD"]),
        },
    }
    with open(HERE / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    show = comp.drop(columns=["is_incumbent"]).copy()
    for c in show.columns:
        if show[c].dtype == float:
            show[c] = show[c].round(4)
    print(show.to_string(index=False))
    print("\nIncumbent row:")
    print(comp[comp["is_incumbent"]].drop(columns=["is_incumbent"]).to_string(index=False))


if __name__ == "__main__":
    main()
