"""Phase 5 — Expanded PBO & selection-bias sensitivity.

Three nested universes, all on the SAME 2558-day index (2016-01-04..2026-03-06), same return
definition (daily LS on fwd_ret_5), same selection objectives (Sharpe; Calmar = CAGR/|MDD|):

  A. Original 71-candidate overlay grid (reproduces exp_007_advanced_validation).
  B. Expanded VERIFIED family = A + the 12 documented Project-04 portfolio-construction trials
     (the exp_004 strategy_timeseries: ls_20/30, blends, +sqrt/pow overlays). 83 candidates.
     These are a genuine, separately-documented selection layer (portfolio construction) that
     demonstrably influenced the shipped design (the 60/40 blend was chosen there).
  C. Conservative sensitivity for the UNOBSERVED search: effective number of independent trials
     from the candidate correlation spectrum, and a Bonferroni-style inflation showing how the
     low PBO would have to be read if the true (unreconstructable) search were N_eff-wide.

Reports Sharpe- and Calmar-objective PBO for A and B. CSCV is non-chronological -> research
robustness, not a live replica. PBO here is a LOWER BOUND: the P04 feature/model search
(OLS-vs-ridge, feature-set choice, the sign-flip decision) and the P05 overlay-FORM search are
NOT in the matrix. Does not tune or re-select anything.

Outputs: reports/PBO_EXPANDED_RESULTS.csv, data/pbo_candidate_corr.csv
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import numpy as np, pandas as pd

ROOT = Path("/Users/rawls/quant-lab")
import sys; sys.path.insert(0, str(ROOT))
from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return
from src.statistics.backtest_overfitting import pbo_cscv, sharpe_objective

E5 = ROOT / "experiments/completed/exp_005_risk_engine_final"
E4 = ROOT / "experiments/completed/exp_004_project04_final/strategy_timeseries"
OUT = ROOT / "experiments/completed/exp_007_full_pipeline_validation"
PPY, S_CSCV = 252, 16
FLOORS = [0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6]; KS = [3, 4, 5, 6, 7]


def canonical_base():
    dep = pd.read_csv(E5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(E5 / "final_daily_weights.csv", parse_dates=["Date"])
    dates = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index().index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float); exp = dep["portfolio_dd_exposure"].astype(float)
    return pr / exp, pr, dates


def vol_mult(base):
    rv = base.rolling(252).std() * np.sqrt(PPY)
    return ((rv / rv.mean()) ** 0.5).clip(0.7, 1.3).fillna(1.0)


def overlay_grid():
    base, pr, dates = canonical_base()
    dd = compute_drawdown((1 + base).cumprod()); m = vol_mult(base)
    cols = {"V1_incumbent": pr.to_numpy()}
    for f in FLOORS:
        for k in KS:
            e_dd = pd.Series(drawdown_exposure_smooth(dd, f, k), index=dates).fillna(1.0)
            cols[f"dd_f{f}_k{k}"] = apply_exposure_to_return(base, e_dd).to_numpy()
            e_cm = (m * drawdown_exposure_smooth(dd, f, k)).clip(0.5, 1.3).fillna(1.0)
            cols[f"comb_f{f}_k{k}"] = apply_exposure_to_return(base, e_cm).to_numpy()
    return pd.DataFrame(cols, index=dates), dates


def p04_family(dates):
    cols = {}
    for f in sorted(E4.glob("*.csv")):
        r = pd.read_csv(f)["portfolio_return"].to_numpy()
        if len(r) == len(dates):
            cols[f"p04_{f.stem}"] = r
    return pd.DataFrame(cols, index=dates)


def calmar_objective(block, periods_per_year=PPY):
    out = np.empty(block.shape[1])
    for j in range(block.shape[1]):
        r = block[:, j]; eq = np.cumprod(1 + r)
        mdd = (eq / np.maximum.accumulate(eq) - 1).min()
        cagr = eq[-1] ** (periods_per_year / len(r)) - 1
        out[j] = cagr / abs(mdd) if mdd < 0 else np.inf
    return out


def run_pbo(M, label):
    names = list(M.columns); Mv = M.to_numpy(); rows = []
    for obj_name, obj in [("sharpe", sharpe_objective), ("calmar", calmar_objective)]:
        res = pbo_cscv(Mv, S=S_CSCV, objective=obj)
        top = Counter(names[i] for i in res.is_selected).most_common(3)
        rows.append({"universe": label, "objective": obj_name, "n_candidates": res.n_strategies,
                     "n_splits": res.n_splits, "PBO": round(res.pbo, 4),
                     "prob_selected_OOS_loss": round(res.prob_oos_loss, 4),
                     "median_OOS_rank_of_selected": round(res.median_oos_of_selected, 4),
                     "most_selected_IS": "; ".join(f"{n}:{c}" for n, c in top)})
    return rows


def effective_n_independent(M):
    """Effective # independent trials from the eigenvalue spectrum of the return correlation."""
    C = np.corrcoef(M.to_numpy().T)
    ev = np.linalg.eigvalsh(C); ev = ev[ev > 0]
    p = M.shape[1]
    # participation-ratio effective dimension and the Kaiser (eigenvalue>1) count
    pr_eff = (ev.sum() ** 2) / (ev ** 2).sum()
    kaiser = int((ev > 1).sum())
    mean_abs_corr = float(np.abs(C[np.triu_indices_from(C, 1)]).mean())
    return {"n_nominal": p, "participation_ratio_eff": round(float(pr_eff), 2),
            "kaiser_eff": kaiser, "mean_abs_pairwise_corr": round(mean_abs_corr, 3)}


def main():
    A, dates = overlay_grid()
    P04 = p04_family(dates)
    B = pd.concat([A, P04], axis=1)
    print(f"A overlay grid: {A.shape[1]} candidates | P04 family: {P04.shape[1]} | B expanded: {B.shape[1]}")

    rows = run_pbo(A, "A_overlay_grid_71") + run_pbo(B, f"B_expanded_verified_{B.shape[1]}")
    # P04 family alone (its own selection step)
    rows += run_pbo(P04, f"B_p04_family_{P04.shape[1]}")
    tbl = pd.DataFrame(rows)
    tbl.to_csv(OUT / "reports/PBO_EXPANDED_RESULTS.csv", index=False)

    effA = effective_n_independent(A); effB = effective_n_independent(B); effP = effective_n_independent(P04)
    corr = pd.DataFrame(np.corrcoef(B.to_numpy().T), index=B.columns, columns=B.columns)
    corr.to_csv(OUT / "data/pbo_candidate_corr.csv")

    print("\n=== PBO by universe ===")
    print(tbl.to_string(index=False))
    print("\n=== effective diversity (participation ratio / Kaiser / mean|corr|) ===")
    for lab, e in [("A_overlay71", effA), ("B_expanded", effB), ("P04_family", effP)]:
        print(f"  {lab:12s}: nominal {e['n_nominal']:>3d}  eff(PR) {e['participation_ratio_eff']:>5}  "
              f"eff(Kaiser) {e['kaiser_eff']:>2d}  mean|corr| {e['mean_abs_pairwise_corr']}")

    import json
    (OUT / "reports/_p5_effective_n.json").write_text(json.dumps(
        {"A_overlay71": effA, "B_expanded": effB, "P04_family": effP}, indent=2))


if __name__ == "__main__":
    main()
