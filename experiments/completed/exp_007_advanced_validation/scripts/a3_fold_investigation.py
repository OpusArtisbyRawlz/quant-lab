"""Stage A3 — investigate the 3 walk-forward folds where DD Only did not improve Sharpe.

Reconstructs the canonical base, the DD-Only (floor0.3,k5) overlay and the incumbent (V1) on the
exact fold test windows from walk_forward_folds.csv, and reports per fold: OOS annualized return,
vol, Sharpe, MDD, mean exposure, and the DD Only-minus-incumbent differences. Does NOT re-optimise
anything — pure diagnostics. Output: data/a3_fold_diagnostics.csv
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[4]
import sys; sys.path.insert(0, str(ROOT))
from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return
from src.utils.metrics import sharpe_ratio, annualized_return, annualized_volatility, max_drawdown

EXP5 = ROOT / "experiments/completed/exp_005_risk_engine_final"
OV = ROOT / "experiments/completed/exp_006_deployment_overlay_challenge"
NEW = Path(__file__).resolve().parents[1]
PPY = 252


def main():
    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    dates = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index().index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)
    base = pr / exp                                   # canonical same-row inverse
    dd = compute_drawdown((1 + base).cumprod())
    e_dd = pd.Series(drawdown_exposure_smooth(dd, 0.3, 5), index=dates).fillna(1.0)
    dd_only = apply_exposure_to_return(base, e_dd)     # DD Only returns
    incum = pr                                         # V1 incumbent (shipped)
    e_inc = exp

    folds = pd.read_csv(OV / "walk_forward_folds.csv")
    rows = []
    for _, f in folds.iterrows():
        s, e = pd.Timestamp(f["test_start"]), pd.Timestamp(f["test_end"])
        m = (dates >= s) & (dates <= e)
        rd, ri = dd_only[m], incum[m]
        ed, ei = e_dd[m], e_inc[m]
        rows.append({
            "fold": int(f["fold"]), "test_start": f["test_start"], "test_end": f["test_end"],
            "n_days": int(m.sum()),
            "incumbent_ann_ret": round(float(annualized_return(ri, PPY)), 4),
            "dd_only_ann_ret": round(float(annualized_return(rd, PPY)), 4),
            "d_ann_ret": round(float(annualized_return(rd, PPY) - annualized_return(ri, PPY)), 4),
            "incumbent_vol": round(float(annualized_volatility(ri, PPY)), 4),
            "dd_only_vol": round(float(annualized_volatility(rd, PPY)), 4),
            "incumbent_sharpe": round(float(sharpe_ratio(ri, PPY)), 4),
            "dd_only_sharpe": round(float(sharpe_ratio(rd, PPY)), 4),
            "d_sharpe": round(float(sharpe_ratio(rd, PPY) - sharpe_ratio(ri, PPY)), 4),
            "incumbent_mdd": round(float(max_drawdown((1 + ri).cumprod())), 4),
            "dd_only_mdd": round(float(max_drawdown((1 + rd).cumprod())), 4),
            "d_mdd_shallower": round(float(max_drawdown((1 + rd).cumprod()) - max_drawdown((1 + ri).cumprod())), 4),
            "dd_only_mean_exposure": round(float(ed.mean()), 4),
            "incumbent_mean_exposure": round(float(ei.mean()), 4),
            "regime": ("down/negative" if annualized_return(ri, PPY) < 0 else "up/positive"),
        })
    df = pd.DataFrame(rows)
    df.to_csv(NEW / "data/a3_fold_diagnostics.csv", index=False)
    pd.set_option("display.width", 240, "display.max_columns", 30)
    print(df.to_string(index=False))
    miss = df[df["d_sharpe"] <= 0]
    # d_mdd_shallower > 0  <=>  DD Only MDD less negative (shallower) than incumbent
    print("\nSharpe-miss folds:", list(miss["fold"]),
          "| all 7 folds MDD shallower?", bool((df["d_mdd_shallower"] >= 0).all()),
          "| of the Sharpe-miss folds, higher DD-Only return in:",
          list(miss[miss["d_ann_ret"] > 0]["fold"]))


if __name__ == "__main__":
    main()
