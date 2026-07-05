"""
Paired circular-block bootstrap: is the DD-Only challenger's edge over the
shipped deployment candidate statistically meaningful, or noise?

Both series are scalings of the SAME recovered base, on the SAME dates, so we
resample identical contiguous time-blocks for both (paired) and recompute the
Sharpe and MDD *differentials* on each resample. Block length preserves the
autocorrelation that drives drawdowns.
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

EXP5 = PROJECT_ROOT / "experiments/completed/exp_005_risk_engine_final"
PPY = 252
N_BOOT = 5000
BLOCK = 21
SEED = 7


def mdd_from_ret(r):
    eq = (1 + r).cumprod()
    return max_drawdown(eq)


def main():
    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    dates = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index().index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)

    base_ret = pr / exp.shift(1).fillna(1.0)
    base_eq = (1 + base_ret).cumprod()
    dd = compute_drawdown(base_eq)

    incumbent = pr.values
    dd_only = apply_exposure_to_return(
        base_ret, drawdown_exposure_smooth(dd, floor=0.3, k=5)
    ).values

    n = len(incumbent)
    s_inc = sharpe_ratio(pd.Series(incumbent), PPY)
    s_dd = sharpe_ratio(pd.Series(dd_only), PPY)
    m_inc = mdd_from_ret(pd.Series(incumbent))
    m_dd = mdd_from_ret(pd.Series(dd_only))

    print(f"Point estimates (n={n} days)")
    print(f"  Incumbent : Sharpe {s_inc:.4f}  MDD {m_inc:.4f}")
    print(f"  DD Only   : Sharpe {s_dd:.4f}  MDD {m_dd:.4f}")
    print(f"  Delta     : Sharpe {s_dd-s_inc:+.4f}  MDD {m_dd-m_inc:+.4f} "
          f"(negative MDD delta = shallower = better)")

    rng = np.random.default_rng(SEED)
    n_blocks = int(np.ceil(n / BLOCK))
    d_sharpe = np.empty(N_BOOT)
    d_mdd = np.empty(N_BOOT)
    for b in range(N_BOOT):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([(np.arange(s, s + BLOCK) % n) for s in starts])[:n]
        ri = pd.Series(incumbent[idx])
        rd = pd.Series(dd_only[idx])
        d_sharpe[b] = sharpe_ratio(rd, PPY) - sharpe_ratio(ri, PPY)
        d_mdd[b] = mdd_from_ret(rd) - mdd_from_ret(ri)

    def ci(x):
        return np.percentile(x, 2.5), np.percentile(x, 97.5)

    sh_lo, sh_hi = ci(d_sharpe)
    md_lo, md_hi = ci(d_mdd)
    p_sharpe_worse = float(np.mean(d_sharpe <= 0))     # challenger Sharpe not better
    # positive ΔMDD = less-negative = shallower = better; "not improved" is ΔMDD <= 0
    p_mdd_worse = float(np.mean(d_mdd <= 0))           # challenger MDD not shallower

    print(f"\nBlock bootstrap (N={N_BOOT}, block={BLOCK}d, paired)")
    print(f"  ΔSharpe  mean {d_sharpe.mean():+.4f}  95% CI [{sh_lo:+.4f}, {sh_hi:+.4f}]")
    print(f"           P(challenger NOT better Sharpe) = {p_sharpe_worse:.4f}")
    print(f"  ΔMDD     mean {d_mdd.mean():+.4f}  95% CI [{md_lo:+.4f}, {md_hi:+.4f}]")
    print(f"           P(challenger NOT shallower MDD) = {p_mdd_worse:.4f}")

    out = pd.DataFrame({
        "metric": ["Sharpe", "MDD"],
        "incumbent": [s_inc, m_inc],
        "challenger_dd_only": [s_dd, m_dd],
        "delta": [s_dd - s_inc, m_dd - m_inc],
        "boot_mean_delta": [d_sharpe.mean(), d_mdd.mean()],
        "ci_lo": [sh_lo, md_lo],
        "ci_hi": [sh_hi, md_hi],
        "p_not_improved": [p_sharpe_worse, p_mdd_worse],
    })
    out.to_csv(Path(__file__).resolve().parent / "significance_dd_only_vs_incumbent.csv",
               index=False)
    print("\nsaved significance_dd_only_vs_incumbent.csv")


if __name__ == "__main__":
    main()
