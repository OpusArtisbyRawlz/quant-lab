"""
Materialise the promoted deployment candidate (DD-Only overlay, floor=0.3, k=5)
from the exp_005 base. Run ONLY after walk_forward_sensitivity.py reports an
overall PASS (guarded below). exp_005 is left untouched as the historical
baseline; the new candidate is written here as a separate, additive artifact.
"""
from pathlib import Path
import sys
import json
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PROJECT_ROOT))

from src.risk.drawdown import (
    compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return,
)
from src.utils.metrics import (
    sharpe_ratio, max_drawdown, annualized_return, annualized_volatility,
)

HERE = Path(__file__).resolve().parent
EXP5 = PROJECT_ROOT / "experiments/completed/exp_005_risk_engine_final"
FLOOR, K = 0.30, 5
PPY = 252


def main():
    gate = json.load(open(HERE / "promotion_gate_result.json"))
    assert gate["overall_pass"], "promotion gate did not pass; refusing to promote"

    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    wide = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index()
    dates = wide.index
    dep.index = dates

    pr = dep["portfolio_return"].astype(float)
    exp_inc = dep["portfolio_dd_exposure"].astype(float)

    # recovered shared base (strip ONLY the portfolio-level overlay)
    base_ret = pr / exp_inc.shift(1).fillna(1.0)
    base_book = wide.div(exp_inc, axis=0)

    # DD-Only overlay
    dd = compute_drawdown((1 + base_ret).cumprod())
    e = drawdown_exposure_smooth(dd, floor=FLOOR, k=K)
    cand_ret = apply_exposure_to_return(base_ret, e)          # lagged
    cand_book = base_book.mul(e, axis=0)                       # contemporaneous
    cand_eq = (1 + cand_ret).cumprod()

    # --- write candidate return series (mirrors incumbent file schema + date) ---
    out_ret = pd.DataFrame({
        "date": dates,
        "portfolio_return": cand_ret.values,
        "equity_curve": cand_eq.values,
        "dd_only_exposure": e.values,
    })
    out_ret.to_csv(HERE / "deployment_candidate_dd_only_returns.csv", index=False)

    # --- write candidate weights (long, mirrors final_daily_weights schema) ---
    cand_long = (cand_book.reset_index()
                 .melt(id_vars="Date", var_name="Ticker", value_name="Weight")
                 .sort_values(["Date", "Ticker"]))
    cand_long.to_csv(HERE / "deployment_candidate_dd_only_weights.csv", index=False)

    # --- metrics ---
    def m(r):
        r = pd.Series(r); eq = (1 + r).cumprod()
        cagr = annualized_return(r, PPY); mdd = max_drawdown(eq)
        return {"Sharpe": float(sharpe_ratio(r, PPY)), "CAGR": float(cagr),
                "MDD": float(mdd), "Calmar": float(cagr / abs(mdd)),
                "Vol": float(annualized_volatility(r, PPY))}

    config = {
        "candidate": "weighted_multi_strategy_with_dd_only_portfolio_overlay",
        "status": "PROMOTED (lead deployment candidate) — exp_006_deployment_overlay_challenge",
        "promoted_over": "exp_005_risk_engine_final/weighted_multi_strategy_with_strategy_and_portfolio_smooth_dd",
        "historical_baseline_retained": "experiments/completed/exp_005_risk_engine_final/ (untouched)",
        "portfolio_level_overlay": {
            "method": "drawdown_exposure_smooth (DD-only, no vol scaling, no clip)",
            "floor": FLOOR, "k": K,
            "application": "exposure lagged 1 day (apply_exposure_to_return)",
        },
        "base": {
            "source": "exp_005 dual-layer product, portfolio-level overlay stripped",
            "base_return": "portfolio_return_t / exposure_{t-1}",
            "base_book": "final_weight_t / exposure_t",
        },
        "n_days": int(len(dates)),
        "date_range": [str(dates[0].date()), str(dates[-1].date())],
        "metrics_full_sample": {
            "candidate_dd_only": m(cand_ret),
            "incumbent_baseline": m(pr),
        },
        "promotion_gate": gate,
        "promotion_caveat": (
            "floor selected in-sample; walk-forward optimiser preferred the grid "
            "lower boundary (floor=0.2). (0.3,5) is a conservative point that still "
            "beats the baseline OOS in 6/7 folds (Sharpe) and 7/7 (MDD). Re-fit "
            "floor/k on new data periodically before live capital changes."
        ),
    }
    json.dump(config, open(HERE / "deployment_candidate_config.json", "w"), indent=2)

    print("Promoted candidate written:")
    print("  deployment_candidate_dd_only_returns.csv  rows:", len(out_ret))
    print("  deployment_candidate_dd_only_weights.csv  rows:", len(cand_long))
    print("  deployment_candidate_config.json")
    print("\nCandidate:", m(cand_ret))
    print("Baseline :", m(pr))


if __name__ == "__main__":
    main()
