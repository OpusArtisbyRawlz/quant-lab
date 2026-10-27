"""Stage B — SELECTION-LEVEL CPCV + PBO on the overlay candidate family.

Research question: how overfit is the SELECTION of a risk-overlay candidate over V1? Unit of
observation = daily portfolio return of a candidate. Trial universe = the DOCUMENTED overlay search
grid reconstructed on the canonical base: floor in {0.2,0.25,0.3,0.35,0.4,0.5,0.6} x k in {3..7},
in both overlay forms (DD-only smooth; vol-combined clip 0.5-1.3), plus V1 (incumbent). = 71 trials.

PBO is estimated by CSCV (Bailey-Lopez de Prado) under two objectives, because the research
decision is drawdown-aware, not pure-Sharpe:
  * Sharpe objective (naive performance-chasing selection)
  * Calmar objective (CAGR / |MDD|, the drawdown-constrained objective this project actually uses)

CRITICAL LIMITATION (reported): this is the overlay search grid only. The original P04 feature/
model search and P05 overlay-FORM search cannot be fully reconstructed, so the true selection
universe is larger and this PBO is a LOWER BOUND on selection complexity. CSCV uses non-chronological
IS/OOS unions -> this is a research robustness test, not a live-trading replica.

Outputs: data/pbo_results.csv, data/selection_cpcv_oos.csv
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[4]
import sys; sys.path.insert(0, str(ROOT))
from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return
from src.statistics.backtest_overfitting import pbo_cscv, sharpe_objective

EXP5 = ROOT / "experiments/completed/exp_005_risk_engine_final"
NEW = Path(__file__).resolve().parents[1]
PPY = 252
FLOORS = [0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6]
KS = [3, 4, 5, 6, 7]
S_CSCV = 16


def canonical_base():
    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    dates = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index().index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)
    return pr / exp, pr, dates


def vol_mult(base):
    rv = base.rolling(252).std() * np.sqrt(PPY)
    return ((rv / rv.mean()) ** 0.5).clip(0.7, 1.3).fillna(1.0)


def build_universe():
    base, pr, dates = canonical_base()
    dd = compute_drawdown((1 + base).cumprod()); m = vol_mult(base)
    cols = {"V1_incumbent": pr.to_numpy()}
    for f in FLOORS:
        for k in KS:
            e_dd = pd.Series(drawdown_exposure_smooth(dd, f, k), index=dates).fillna(1.0)
            cols[f"dd_f{f}_k{k}"] = apply_exposure_to_return(base, e_dd).to_numpy()
            e_cm = (m * drawdown_exposure_smooth(dd, f, k)).clip(0.5, 1.3).fillna(1.0)
            cols[f"comb_f{f}_k{k}"] = apply_exposure_to_return(base, e_cm).to_numpy()
    M = pd.DataFrame(cols, index=dates)
    return M


def calmar_objective(block, periods_per_year=PPY):
    # per column: CAGR / |MDD| over the pooled block rows
    out = np.empty(block.shape[1])
    for j in range(block.shape[1]):
        r = block[:, j]
        eq = np.cumprod(1 + r)
        mdd = (eq / np.maximum.accumulate(eq) - 1).min()
        n = len(r)
        cagr = eq[-1] ** (periods_per_year / n) - 1
        out[j] = cagr / abs(mdd) if mdd < 0 else np.inf
    return out


def main():
    M = build_universe()
    names = list(M.columns)
    Mv = M.to_numpy()
    print(f"universe: {Mv.shape[1]} candidates x {Mv.shape[0]} days  (grid {len(FLOORS)}x{len(KS)} x2 forms + V1)")

    rows, oos_rows = [], []
    for obj_name, obj in [("sharpe", sharpe_objective), ("calmar", calmar_objective)]:
        res = pbo_cscv(Mv, S=S_CSCV, objective=obj)
        sel_names = [names[i] for i in res.is_selected]
        from collections import Counter
        top = Counter(sel_names).most_common(3)
        rows.append({"objective": obj_name, "n_candidates": res.n_strategies, "S": res.S,
                     "n_splits": res.n_splits, "PBO": round(res.pbo, 4),
                     "median_logit": round(float(np.median(res.logits)), 4),
                     "prob_selected_OOS_loss": round(res.prob_oos_loss, 4),
                     "median_OOS_of_selected": round(res.median_oos_of_selected, 4),
                     "most_selected_IS": "; ".join(f"{n}:{c}" for n, c in top)})
        oos_rows.append({"objective": obj_name,
                         "oos_rank_mean": round(float(res.oos_relative_ranks.mean()), 4),
                         "oos_rank_p05": round(float(np.percentile(res.oos_relative_ranks, 5)), 4),
                         "oos_rank_p95": round(float(np.percentile(res.oos_relative_ranks, 95)), 4),
                         "frac_splits_selected_below_median": round(float(np.mean(res.logits <= 0)), 4)})
    pbo_tbl = pd.DataFrame(rows); pbo_tbl.to_csv(NEW / "data/pbo_results.csv", index=False)
    cpcv_tbl = pd.DataFrame(oos_rows); cpcv_tbl.to_csv(NEW / "data/selection_cpcv_oos.csv", index=False)
    print("\n=== B5 PBO (CSCV) on overlay candidate selection ===")
    print(pbo_tbl.to_string(index=False))
    print("\n=== B4 selection-level OOS rank distribution of IS-selected candidate ===")
    print(cpcv_tbl.to_string(index=False))

    # where does V1 rank, and where do the 3 named candidates sit, on full-sample objectives?
    full_sharpe = sharpe_objective(Mv); full_calmar = calmar_objective(Mv)
    named = {"V1_incumbent": "V1", "dd_f0.3_k5": "DD Only", "comb_f0.3_k5": "Combined"}
    print("\n=== full-sample rank of the 3 decision candidates (of 71) ===")
    for col, lab in named.items():
        j = names.index(col)
        sr_rank = int((full_sharpe > full_sharpe[j]).sum()) + 1
        cal_rank = int((full_calmar > full_calmar[j]).sum()) + 1
        print(f"  {lab:9} ({col}): Sharpe {full_sharpe[j]:.3f} rank {sr_rank}/71 | "
              f"Calmar {full_calmar[j]:.3f} rank {cal_rank}/71")


if __name__ == "__main__":
    main()
