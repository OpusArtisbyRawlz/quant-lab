"""
exp_006 tournament — walk-forward parameter stability of the winning overlay
family (smooth DD floor/k) on BOTH candidate bases.

For each base (deployment, v2) we:
  * grid-score Sharpe/MDD over a floor x k neighbourhood on the full sample, and
  * run an expanding-window walk-forward: select (floor,k) by *training* Sharpe,
    score the held-out test window of the fully-causal candidate series, and
    compare to V1 on that same test window.

Because the overlay is online (drawdown from causal cummax, exposure lagged one
day) selecting params on a training slice and scoring the next slice of the full
causal series is leakage-free.

Outputs:
  walk_forward_stability.csv   per (base, fold): selected floor/k, test Sharpe/MDD
  param_grid_stability.csv     per (base, floor, k): full-sample Sharpe/MDD
"""

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PROJECT_ROOT))

from src.risk.drawdown import (
    compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return,
)
from src.utils.metrics import sharpe_ratio, max_drawdown, annualized_return

HERE = Path(__file__).resolve().parent
EXP5 = PROJECT_ROOT / "experiments/completed/exp_005_risk_engine_final"
PPY = 252
FLOOR_GRID = [0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
K_GRID = [3, 4, 5, 6, 7]
INIT_TRAIN = 756
TEST = 252
STEP = 252


def mdd(r):
    return max_drawdown((1 + pd.Series(r)).cumprod())


def load_bases():
    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    dates = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index().index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)
    base_dep = pr / exp.shift(1).fillna(1.0)
    v2 = pd.read_csv(EXP5 / "final_returns_v2_with_dates.csv")
    v2["date"] = pd.to_datetime(v2["date"])
    v2 = v2.set_index("date")["returns"].astype(float)
    return {"deployment": base_dep, "v2": v2}, pr, dates


def cand_series(base_ret, floor, k):
    dd = compute_drawdown((1 + base_ret).cumprod())
    e = drawdown_exposure_smooth(dd, floor=floor, k=k)
    return apply_exposure_to_return(base_ret, e)


def main():
    bases, v1, dates = load_bases()
    n = len(dates)

    # ---- full-sample neighbourhood grid ----
    grid_rows = []
    for bname, br in bases.items():
        for fl in FLOOR_GRID:
            for k in K_GRID:
                r = cand_series(br, fl, k)
                grid_rows.append({
                    "base": bname, "floor": fl, "k": k,
                    "Sharpe": sharpe_ratio(r, PPY), "MDD": mdd(r),
                    "CAGR": annualized_return(r, PPY),
                })
    grid = pd.DataFrame(grid_rows)
    grid.to_csv(HERE / "param_grid_stability.csv", index=False)

    # ---- walk-forward (select by train Sharpe, score test) ----
    wf_rows = []
    starts = list(range(INIT_TRAIN, n - TEST + 1, STEP))
    for bname, br in bases.items():
        # precompute full causal candidate series per (floor,k)
        series = {(fl, k): cand_series(br, fl, k).values
                  for fl in FLOOR_GRID for k in K_GRID}
        for tr_end in starts:
            tr = slice(0, tr_end)
            te = slice(tr_end, tr_end + TEST)
            best, best_sh = None, -np.inf
            for key, arr in series.items():
                s = sharpe_ratio(pd.Series(arr[tr]), PPY)
                if s > best_sh:
                    best_sh, best = s, key
            arr = series[best]
            r_te = pd.Series(arr[te]); v1_te = pd.Series(v1.values[te])
            wf_rows.append({
                "base": bname,
                "test_start": str(dates[tr_end].date()),
                "test_end": str(dates[min(tr_end + TEST, n) - 1].date()),
                "sel_floor": best[0], "sel_k": best[1],
                "test_Sharpe": sharpe_ratio(r_te, PPY),
                "test_MDD": mdd(r_te.values),
                "V1_test_Sharpe": sharpe_ratio(v1_te, PPY),
                "V1_test_MDD": mdd(v1_te.values),
                "dSharpe_vs_V1": sharpe_ratio(r_te, PPY) - sharpe_ratio(v1_te, PPY),
                "dMDD_vs_V1": mdd(r_te.values) - mdd(v1_te.values),
            })
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(HERE / "walk_forward_stability.csv", index=False)

    # ---- summaries ----
    print("=== full-sample neighbourhood grid: spread per base ===")
    for bname, g in grid.groupby("base"):
        nb = g[(g.floor.between(0.25, 0.35)) & (g.k.between(4, 6))]
        print(f"  {bname:11s} grid Sharpe [{g.Sharpe.min():.3f},{g.Sharpe.max():.3f}] "
              f"neighbourhood(0.25-0.35,4-6) spread {nb.Sharpe.max()-nb.Sharpe.min():.3f}")

    print("\n=== walk-forward vs V1 (per base) ===")
    for bname, g in wf.groupby("base"):
        print(f"  {bname:11s} folds={len(g)} "
              f"Sharpe>V1 {int((g.dSharpe_vs_V1>0).sum())}/{len(g)} "
              f"MDD shallower {int((g.dMDD_vs_V1>0).sum())}/{len(g)} "
              f"meanDSharpe {g.dSharpe_vs_V1.mean():+.3f} "
              f"sel_floor mode {g.sel_floor.mode().iloc[0]} sel_k mode {g.sel_k.mode().iloc[0]}")
    print("\nwalk_forward_stability.csv, param_grid_stability.csv written.")


if __name__ == "__main__":
    main()
