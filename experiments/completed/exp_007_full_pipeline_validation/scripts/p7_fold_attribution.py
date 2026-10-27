"""Phase 7 — Attribution of DD Only's 3 Sharpe-underperformance folds.

Preserves the 6/7 gate and its failure; does NOT re-optimise. For each of the 7 walk-forward folds
(gate windows), decomposes the DD-Only-minus-incumbent Sharpe gap into interpretable channels:
  * exposure channel: DD Only mean exposure on base UP-days vs DOWN-days (does it de-risk into
    profit or into loss?);
  * return decomposition: cumulative (dd_only - incumbent) return contributed on positive-base days
    (opportunity cost) vs negative-base days (loss avoided);
  * volatility channel: realized-vol reduction;
  * recovery channel: longest-underwater day count;
  * cost channel: added turnover proxy = mean |Delta exposure| (DD Only varies exposure daily; V1's
    exposure path is its own shipped overlay);
  * Sharpe-sign artifact flag: in negative-mean-return folds, de-risking can LOWER Sharpe while
    improving economics (less loss, shallower DD) -> flagged explicitly.

Folds are consecutive calendar years on an OVERLAPPING 5-day-label series -> adjacent folds share
label/regime information and are NOT independent; the 4/7 count is not a 7-trial binomial.

Output: reports/DD_ONLY_FOLD_ATTRIBUTION.csv (+ json summary)
"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np, pandas as pd

ROOT = Path("/Users/rawls/quant-lab")
import sys; sys.path.insert(0, str(ROOT))
from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return
from src.utils.metrics import sharpe_ratio, annualized_return, annualized_volatility, max_drawdown

E5 = ROOT / "experiments/completed/exp_005_risk_engine_final"
OV = ROOT / "experiments/completed/exp_006_deployment_overlay_challenge"
OUT = ROOT / "experiments/completed/exp_007_full_pipeline_validation"
PPY = 252


def longest_underwater(ret):
    eq = (1 + ret).cumprod().to_numpy()
    peak = np.maximum.accumulate(eq)
    uw = eq < peak * (1 - 1e-12)
    best = cur = 0
    for v in uw:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return int(best)


def main():
    dep = pd.read_csv(E5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(E5 / "final_daily_weights.csv", parse_dates=["Date"])
    dates = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index().index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float); exp = dep["portfolio_dd_exposure"].astype(float)
    base = pr / exp
    dd = compute_drawdown((1 + base).cumprod())
    e_dd = pd.Series(drawdown_exposure_smooth(dd, 0.3, 5), index=dates).fillna(1.0)
    dd_only = apply_exposure_to_return(base, e_dd)
    incum, e_inc = pr, exp
    # executed exposures are lagged one day (apply_exposure_to_return shifts); align base sign to execution
    e_dd_exec = e_dd.shift(1).fillna(1.0)
    base_lag = base  # base return realized same day as executed exposure acts on it

    folds = pd.read_csv(OV / "walk_forward_folds.csv")
    rows = []
    for _, f in folds.iterrows():
        s, e = pd.Timestamp(f["test_start"]), pd.Timestamp(f["test_end"])
        m = (dates >= s) & (dates <= e)
        rd, ri = dd_only[m], incum[m]
        b = base_lag[m]; ed = e_dd_exec[m]
        up = b > 0; dn = b < 0
        d_ret = (rd - ri)
        row = {
            "fold": int(f["fold"]), "regime": "neg" if annualized_return(ri, PPY) < 0 else "pos",
            "d_sharpe": round(float(sharpe_ratio(rd, PPY) - sharpe_ratio(ri, PPY)), 4),
            "d_ann_ret_pp": round(float((annualized_return(rd, PPY) - annualized_return(ri, PPY)) * 100), 2),
            "d_mdd_shallower_pp": round(float((max_drawdown((1 + rd).cumprod()) - max_drawdown((1 + ri).cumprod())) * 100), 2),
            "vol_reduction_pp": round(float((annualized_volatility(ri, PPY) - annualized_volatility(rd, PPY)) * 100), 2),
            "dd_exp_on_up": round(float(ed[up].mean()), 3), "dd_exp_on_down": round(float(ed[dn].mean()), 3),
            "cum_dret_on_up_days_pp": round(float(d_ret[up.values].sum() * 100), 2),   # opportunity cost (<0 = gave up)
            "cum_dret_on_down_days_pp": round(float(d_ret[dn.values].sum() * 100), 2),  # loss avoided (>0 = saved)
            "incum_underwater_days": longest_underwater(ri), "dd_underwater_days": longest_underwater(rd),
            "added_turnover_proxy": round(float(e_dd_exec[m].diff().abs().mean()), 4),
            "sharpe_sign_artifact": bool(annualized_return(ri, PPY) < 0),
        }
        # dominant channel label
        if row["sharpe_sign_artifact"]:
            row["attribution"] = "Sharpe-sign artifact (neg-return fold): DD Only lost less & drew down less; Sharpe worsens mechanically"
        elif row["cum_dret_on_up_days_pp"] < -1.0 and row["d_sharpe"] < 0:
            row["attribution"] = "opportunity cost: de-risked during a profitable year, gave up upside for shallower MDD"
        elif row["d_sharpe"] >= 0:
            row["attribution"] = "Sharpe improved (pass fold)"
        else:
            row["attribution"] = "mild de-risking drag; MDD still shallower"
        rows.append(row)

    tbl = pd.DataFrame(rows)
    tbl.to_csv(OUT / "reports/DD_ONLY_FOLD_ATTRIBUTION.csv", index=False)
    miss = tbl[tbl["d_sharpe"] < 0]
    summary = {
        "n_folds": len(tbl), "sharpe_pass": int((tbl["d_sharpe"] >= 0).sum()),
        "mdd_shallower_all": bool((tbl["d_mdd_shallower_pp"] >= 0).all()),
        "miss_folds": miss["fold"].tolist(),
        "miss_are_negative_regime": int(miss["sharpe_sign_artifact"].sum()),
        "miss_opportunity_cost": int((~miss["sharpe_sign_artifact"] & (miss["cum_dret_on_up_days_pp"] < 0)).sum()),
        "all_folds_vol_reduced": bool((tbl["vol_reduction_pp"] > 0).all()),
        "note": "Folds overlap via 5-day labels and share regime -> not independent; 4/7 is not a binomial.",
    }
    (OUT / "reports/_p7_summary.json").write_text(json.dumps(summary, indent=2))
    print(tbl.to_string(index=False))
    print("\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
