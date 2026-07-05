"""
exp_006 tournament — significance, stability, leakage, and the apples-to-apples
base test.

Four evidence checks, written next to this script:

1. monte_carlo_metrics.csv      Per-candidate i.i.d. bootstrap (N_MC) of Sharpe &
                                MDD -> 95% CIs (sampling stability of each row).

2. significance_vs_v1.csv       Circular block bootstrap (block=BLOCK, N_BOOT) of
                                the Sharpe & MDD *differential* vs Deployment
                                Candidate V1. Group-B challengers share V1's base
                                so blocks are resampled *paired* (identical index
                                blocks for both). The Group-C head-to-head
                                (Historical DD Only vs V1) is on a *different* base
                                series, so it is resampled *independently* and
                                flagged unpaired.

3. base_apples_to_apples.csv    The SAME DD-Only(0.3,5) overlay applied to the
                                deployment base vs the v2 base — isolates how much
                                of Group C's edge is the overlay vs the base.

4. leakage_check.csv            Confirms the overlay is causal: candidate_return_t
                                must equal base_return_t * exposure_{t-1} to
                                numerical precision (no contemporaneous exposure
                                leaking into the same-day return).
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
N_MC = 2000
N_BOOT = 5000
BLOCK = 21
SEED = 7


def mdd(r):
    return max_drawdown((1 + pd.Series(r)).cumprod())


def vol_mult(r, window=252):
    rv = pd.Series(r).rolling(window).std() * np.sqrt(PPY)
    return ((rv / rv.mean()) ** 0.5).clip(0.7, 1.3)


def load():
    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    dates = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index().index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)
    base_ret = pr / exp.shift(1).fillna(1.0)
    v2 = pd.read_csv(EXP5 / "final_returns_v2_with_dates.csv")
    v2["date"] = pd.to_datetime(v2["date"])
    v2 = v2.set_index("date")["returns"].astype(float)
    return pr, base_ret, v2, dates


def candidate_returns(pr, base_ret, v2, dates):
    dep_dd = compute_drawdown((1 + base_ret).cumprod())
    dep_m = vol_mult(base_ret)
    v2_dd = compute_drawdown((1 + v2).cumprod())
    v2_m = vol_mult(v2)

    def dep(e):
        return apply_exposure_to_return(base_ret, pd.Series(e, index=dates).fillna(1.0))

    def hist(e):
        return apply_exposure_to_return(v2, pd.Series(e, index=dates).fillna(1.0))

    cands = {
        "Deployment Candidate V1 (baseline)": (pr.values, True),   # paired-base = deployment
        "DD Only (floor0.3,k5)": (dep(drawdown_exposure_smooth(dep_dd, 0.3, 5)).values, True),
        "Combined DD+Vol (floor0.3,k5,clip0.5-1.3)": (dep((dep_m * drawdown_exposure_smooth(dep_dd, 0.3, 5)).clip(0.5, 1.3)).values, True),
        "Floor 0.5 (m*smooth(0.5,5),clip0.5-1.3)": (dep((dep_m * drawdown_exposure_smooth(dep_dd, 0.5, 5)).clip(0.5, 1.3)).values, True),
        "DD k=1 (m*smooth(0.6,1),clip0.3-1.5)": (dep((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 1)).clip(0.3, 1.5)).values, True),
        "Historical DD Only (floor0.3,k5)": (hist(drawdown_exposure_smooth(v2_dd, 0.3, 5)).values, False),
        "Historical Combined (floor0.3,k5,clip0.5-1.3)": (hist((v2_m * drawdown_exposure_smooth(v2_dd, 0.3, 5)).clip(0.5, 1.3)).values, False),
        "Historical Floor 0.5 (clip0.5-1.3)": (hist((v2_m * drawdown_exposure_smooth(v2_dd, 0.5, 5)).clip(0.5, 1.3)).values, False),
    }
    return cands


def main():
    pr, base_ret, v2, dates = load()
    cands = candidate_returns(pr, base_ret, v2, dates)
    n = len(dates)
    rng = np.random.default_rng(SEED)

    # ---- 1. Monte Carlo i.i.d. bootstrap of each candidate's own metrics ----
    mc_rows = []
    for name, (r, _) in cands.items():
        r = np.asarray(r)
        sh = np.empty(N_MC); md = np.empty(N_MC)
        for b in range(N_MC):
            idx = rng.integers(0, n, size=n)
            rr = pd.Series(r[idx])
            sh[b] = sharpe_ratio(rr, PPY)
            md[b] = mdd(r[idx])
        mc_rows.append({
            "Candidate": name,
            "Sharpe": sharpe_ratio(pd.Series(r), PPY),
            "Sharpe_ci_lo": np.percentile(sh, 2.5), "Sharpe_ci_hi": np.percentile(sh, 97.5),
            "MDD": mdd(r),
            "MDD_ci_lo": np.percentile(md, 2.5), "MDD_ci_hi": np.percentile(md, 97.5),
        })
    pd.DataFrame(mc_rows).to_csv(HERE / "monte_carlo_metrics.csv", index=False)

    # ---- 2. Block bootstrap of the differential vs V1 ----
    v1 = np.asarray(cands["Deployment Candidate V1 (baseline)"][0])
    n_blocks = int(np.ceil(n / BLOCK))

    def block_idx(rng):
        starts = rng.integers(0, n, size=n_blocks)
        return np.concatenate([(np.arange(s, s + BLOCK) % n) for s in starts])[:n]

    sig_rows = []
    rng = np.random.default_rng(SEED)
    for name, (r, paired) in cands.items():
        if name == "Deployment Candidate V1 (baseline)":
            continue
        r = np.asarray(r)
        d_sh = np.empty(N_BOOT); d_md = np.empty(N_BOOT)
        for b in range(N_BOOT):
            if paired:
                idx = block_idx(rng)
                jdx = idx
            else:
                idx = block_idx(rng)   # challenger blocks
                jdx = block_idx(rng)   # independent V1 blocks (different base)
            rc = pd.Series(r[idx]); rv = pd.Series(v1[jdx])
            d_sh[b] = sharpe_ratio(rc, PPY) - sharpe_ratio(rv, PPY)
            d_md[b] = mdd(r[idx]) - mdd(v1[jdx])
        sig_rows.append({
            "Challenger": name,
            "pairing": "paired (same base)" if paired else "UNPAIRED (different base)",
            "Sharpe_V1": sharpe_ratio(pd.Series(v1), PPY),
            "Sharpe_challenger": sharpe_ratio(pd.Series(r), PPY),
            "dSharpe": sharpe_ratio(pd.Series(r), PPY) - sharpe_ratio(pd.Series(v1), PPY),
            "dSharpe_ci_lo": np.percentile(d_sh, 2.5), "dSharpe_ci_hi": np.percentile(d_sh, 97.5),
            "P(dSharpe<=0)": float(np.mean(d_sh <= 0)),
            "MDD_V1": mdd(v1), "MDD_challenger": mdd(r),
            "dMDD": mdd(r) - mdd(v1),
            "dMDD_ci_lo": np.percentile(d_md, 2.5), "dMDD_ci_hi": np.percentile(d_md, 97.5),
            "P(dMDD<=0 not shallower)": float(np.mean(d_md <= 0)),
        })
    pd.DataFrame(sig_rows).to_csv(HERE / "significance_vs_v1.csv", index=False)

    # ---- 3. Apples-to-apples: same DD-Only(0.3,5) overlay on both bases ----
    dep_dd = compute_drawdown((1 + base_ret).cumprod())
    v2_dd = compute_drawdown((1 + v2).cumprod())
    dep_ddonly = apply_exposure_to_return(base_ret, drawdown_exposure_smooth(dep_dd, 0.3, 5))
    v2_ddonly = apply_exposure_to_return(v2, drawdown_exposure_smooth(v2_dd, 0.3, 5))

    def row(label, r):
        r = pd.Series(r)
        return {"series": label, "Sharpe": sharpe_ratio(r, PPY),
                "CAGR": annualized_return(r, PPY), "MDD": mdd(r),
                "Vol": r.std() * np.sqrt(PPY)}
    pd.DataFrame([
        row("deployment base (raw)", base_ret),
        row("v2 base (raw)", v2),
        row("DD-Only(0.3,5) on deployment base", dep_ddonly),
        row("DD-Only(0.3,5) on v2 base", v2_ddonly),
    ]).to_csv(HERE / "base_apples_to_apples.csv", index=False)

    # ---- 4. Leakage / look-ahead check ----
    leak_rows = []
    for label, br, dd in [("deployment", base_ret, dep_dd), ("v2", v2, v2_dd)]:
        e = drawdown_exposure_smooth(dd, 0.3, 5)
        causal = (br * e.shift(1).fillna(1.0))          # manual causal application
        via_fn = apply_exposure_to_return(br, e)        # library application
        contemp = (br * e)                              # same-day (leaky) application
        leak_rows.append({
            "base": label,
            "max_abs_diff_causal_vs_fn": float((causal - via_fn).abs().max()),
            "Sharpe_causal": sharpe_ratio(via_fn, PPY),
            "Sharpe_if_contemporaneous_leak": sharpe_ratio(contemp, PPY),
            "note": "fn lags exposure 1 day; matches manual causal to ~0; "
                    "contemporaneous (leaky) variant shown only to size the gap",
        })
    pd.DataFrame(leak_rows).to_csv(HERE / "leakage_check.csv", index=False)

    print("monte_carlo_metrics.csv, significance_vs_v1.csv, "
          "base_apples_to_apples.csv, leakage_check.csv written.")
    print("\n=== significance vs V1 ===")
    print(pd.DataFrame(sig_rows)[
        ["Challenger", "pairing", "dSharpe", "dSharpe_ci_lo", "dSharpe_ci_hi",
         "P(dSharpe<=0)", "dMDD", "dMDD_ci_lo", "dMDD_ci_hi"]].round(4).to_string(index=False))
    print("\n=== apples-to-apples base test ===")
    print(pd.read_csv(HERE / "base_apples_to_apples.csv").round(4).to_string(index=False))
    print("\n=== leakage check ===")
    print(pd.read_csv(HERE / "leakage_check.csv").to_string(index=False))


if __name__ == "__main__":
    main()
