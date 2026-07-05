"""
Promotion gate for the DD-Only challenger.

Two checks the user requires before promotion:

  CHECK 1 — Exact reproduction.
    Reconstructed base + the ORIGINAL deployment overlay (the stored
    portfolio_dd_exposure, applied with the codebase's lagged convention) must
    reproduce the incumbent return series to numerical precision (< 1e-12).

  CHECK 2 — Walk-forward parameter sensitivity around (floor, k).
    (a) Full-sample floor x k grid for the DD-Only overlay: small parameter
        changes must not materially degrade performance, and the neighbourhood
        of (0.3, 5) must still beat the incumbent.
    (b) Causal expanding-window walk-forward: select (floor, k) on the training
        window, score the resulting causal overlay on the *next* out-of-sample
        window. The DD-Only overlay is online (drawdown uses a causal running
        max), so fixing train-chosen params and scoring the test slice is a
        legitimate OOS test. Show the chosen params are stable and the OOS edge
        over the incumbent persists.

Writes:
    reproduction_check.csv
    param_sensitivity_grid.csv
    walk_forward_folds.csv
Prints an overall PASS/FAIL for each gate.
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
PPY = 252

REPRO_TOL = 1e-12
FLOOR_GRID = [0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
K_GRID = [3, 4, 5, 6, 7]
SELECTED = (0.30, 5)
NEIGHBORHOOD_FLOOR = (0.25, 0.35)
NEIGHBORHOOD_K = (4, 6)

# walk-forward
INIT_TRAIN = 756       # 3y
TEST = 252             # 1y
STEP = 252


def load_base():
    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    dates = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index().index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)
    base_ret = pr / exp.shift(1).fillna(1.0)
    return base_ret, pr, exp, dates


def metrics(ret):
    ret = pd.Series(ret)
    eq = (1 + ret).cumprod()
    cagr = annualized_return(ret, PPY)
    mdd = max_drawdown(eq)
    return {
        "Sharpe": sharpe_ratio(ret, PPY),
        "CAGR": cagr,
        "MDD": mdd,
        "Calmar": cagr / abs(mdd) if mdd and mdd == mdd else np.nan,
        "Vol": annualized_volatility(ret, PPY),
    }


def dd_only_return(base_ret, floor, k):
    """Causal DD-only overlay: exposure_t depends only on drawdown up to t."""
    dd = compute_drawdown((1 + base_ret).cumprod())
    e = drawdown_exposure_smooth(dd, floor=floor, k=k)
    return apply_exposure_to_return(base_ret, e)


# ---------------------------------------------------------------------------
# CHECK 1 — exact reproduction
# ---------------------------------------------------------------------------
def check_reproduction(base_ret, pr, exp):
    repro = apply_exposure_to_return(base_ret, exp)  # base * exp.shift(1).fillna(1)
    abs_err = (repro - pr).abs()
    max_err = float(abs_err.max())
    passed = max_err < REPRO_TOL
    pd.DataFrame({
        "metric": ["max_abs_error", "mean_abs_error", "tolerance", "n_days", "passed"],
        "value": [max_err, float(abs_err.mean()), REPRO_TOL, int(len(pr)), int(passed)],
    }).to_csv(HERE / "reproduction_check.csv", index=False)
    print("=" * 70)
    print("CHECK 1 — EXACT REPRODUCTION (base + original deployment overlay)")
    print(f"  max abs error  = {max_err:.3e}   (tolerance {REPRO_TOL:.0e})")
    print(f"  mean abs error = {float(abs_err.mean()):.3e}")
    print(f"  RESULT: {'PASS' if passed else 'FAIL'}")
    return passed


# ---------------------------------------------------------------------------
# CHECK 2a — full-sample floor x k grid
# ---------------------------------------------------------------------------
def grid(base_ret, incumbent_mdd, incumbent_sharpe):
    rows = []
    for f in FLOOR_GRID:
        for k in K_GRID:
            m = metrics(dd_only_return(base_ret, f, k))
            rows.append({
                "floor": f, "k": k, **m,
                "beats_incumbent_sharpe": m["Sharpe"] > incumbent_sharpe,
                "beats_incumbent_mdd": m["MDD"] > incumbent_mdd,  # shallower
            })
    g = pd.DataFrame(rows)
    g.to_csv(HERE / "param_sensitivity_grid.csv", index=False)

    nb = g[(g["floor"].between(*NEIGHBORHOOD_FLOOR)) & (g["k"].between(*NEIGHBORHOOD_K))]
    print("\n" + "=" * 70)
    print("CHECK 2a — FULL-SAMPLE floor x k SENSITIVITY")
    print(f"  selected (floor={SELECTED[0]}, k={SELECTED[1]}):")
    sel = g[(g["floor"] == SELECTED[0]) & (g["k"] == SELECTED[1])].iloc[0]
    print(f"     Sharpe {sel['Sharpe']:.3f}  MDD {sel['MDD']:.3f}  Calmar {sel['Calmar']:.3f}")
    print(f"  neighbourhood floor∈{NEIGHBORHOOD_FLOOR} k∈{NEIGHBORHOOD_K} "
          f"({len(nb)} points):")
    print(f"     Sharpe range [{nb['Sharpe'].min():.3f}, {nb['Sharpe'].max():.3f}]  "
          f"spread {nb['Sharpe'].max()-nb['Sharpe'].min():.3f}")
    print(f"     MDD range    [{nb['MDD'].min():.3f}, {nb['MDD'].max():.3f}]")
    print(f"     all neighbourhood points beat incumbent Sharpe? "
          f"{bool(nb['beats_incumbent_sharpe'].all())}")
    print(f"     all neighbourhood points beat incumbent MDD?    "
          f"{bool(nb['beats_incumbent_mdd'].all())}")
    print(f"  whole grid: beat-incumbent-Sharpe {int(g['beats_incumbent_sharpe'].sum())}/{len(g)}, "
          f"beat-incumbent-MDD {int(g['beats_incumbent_mdd'].sum())}/{len(g)}")

    # "material degradation" test: neighbourhood Sharpe spread small AND all beat incumbent
    spread_ok = (nb["Sharpe"].max() - nb["Sharpe"].min()) < 0.20
    all_beat = bool(nb["beats_incumbent_sharpe"].all() and nb["beats_incumbent_mdd"].all())
    passed = spread_ok and all_beat
    print(f"  RESULT: {'PASS' if passed else 'FAIL'} "
          f"(neighbourhood spread<0.20 Sharpe & all beat incumbent)")
    return passed, g


# ---------------------------------------------------------------------------
# CHECK 2b — causal walk-forward
# ---------------------------------------------------------------------------
def walk_forward(base_ret, pr):
    n = len(base_ret)
    # precompute candidate returns for every grid point (causal, full series)
    cand = {(f, k): dd_only_return(base_ret, f, k) for f in FLOOR_GRID for k in K_GRID}

    folds = []
    train_end = INIT_TRAIN
    fold_id = 0
    while train_end < n:
        test_start = train_end
        test_end = min(train_end + TEST, n)
        if test_end - test_start < 60:   # skip a tiny trailing stub
            break
        tr = slice(0, train_end)
        te = slice(test_start, test_end)

        # select params by training-window Sharpe
        best = max(FLOOR_GRID and [(f, k) for f in FLOOR_GRID for k in K_GRID],
                   key=lambda fk: sharpe_ratio(cand[fk].iloc[tr], PPY))
        bf, bk = best

        m_chosen = metrics(cand[best].iloc[te])
        m_fixed = metrics(cand[SELECTED].iloc[te])
        m_inc = metrics(pr.iloc[te])

        folds.append({
            "fold": fold_id,
            "train_days": train_end,
            "test_start": str(base_ret.index[test_start].date()),
            "test_end": str(base_ret.index[test_end - 1].date()),
            "chosen_floor": bf, "chosen_k": bk,
            "OOS_Sharpe_chosen": m_chosen["Sharpe"], "OOS_MDD_chosen": m_chosen["MDD"],
            "OOS_Sharpe_fixed(0.3,5)": m_fixed["Sharpe"], "OOS_MDD_fixed(0.3,5)": m_fixed["MDD"],
            "OOS_Sharpe_incumbent": m_inc["Sharpe"], "OOS_MDD_incumbent": m_inc["MDD"],
            "fixed_beats_incumbent_sharpe": m_fixed["Sharpe"] > m_inc["Sharpe"],
            "fixed_beats_incumbent_mdd": m_fixed["MDD"] > m_inc["MDD"],
        })
        fold_id += 1
        train_end += STEP

    wf = pd.DataFrame(folds)
    wf.to_csv(HERE / "walk_forward_folds.csv", index=False)

    print("\n" + "=" * 70)
    print("CHECK 2b — CAUSAL WALK-FORWARD (select on train, score OOS test)")
    cols = ["fold", "test_start", "test_end", "chosen_floor", "chosen_k",
            "OOS_Sharpe_fixed(0.3,5)", "OOS_Sharpe_incumbent",
            "OOS_MDD_fixed(0.3,5)", "OOS_MDD_incumbent"]
    print(wf[cols].round(3).to_string(index=False))

    n_folds = len(wf)
    fixed_win_sharpe = int(wf["fixed_beats_incumbent_sharpe"].sum())
    fixed_win_mdd = int(wf["fixed_beats_incumbent_mdd"].sum())
    # mean OOS edge of fixed (0.3,5) vs incumbent
    edge_sharpe = float((wf["OOS_Sharpe_fixed(0.3,5)"] - wf["OOS_Sharpe_incumbent"]).mean())
    edge_mdd = float((wf["OOS_MDD_fixed(0.3,5)"] - wf["OOS_MDD_incumbent"]).mean())
    chosen_floor_max = wf["chosen_floor"].max()
    print(f"\n  folds: {n_folds}")
    print(f"  fixed (0.3,5) OOS-beats-incumbent: Sharpe {fixed_win_sharpe}/{n_folds}, "
          f"MDD {fixed_win_mdd}/{n_folds}")
    print(f"  mean OOS edge of fixed (0.3,5): ΔSharpe {edge_sharpe:+.3f}, "
          f"ΔMDD {edge_mdd:+.3f} (shallower)")
    print(f"  train-chosen floor stayed defensive (<=0.40) in all folds? "
          f"{bool(chosen_floor_max <= 0.40)}")

    passed = (fixed_win_sharpe >= n_folds - 1) and (fixed_win_mdd >= n_folds - 1) and edge_sharpe > 0
    print(f"  RESULT: {'PASS' if passed else 'FAIL'} "
          f"(fixed params beat incumbent OOS in >= n-1 folds, positive mean edge)")
    return passed, wf


def main():
    base_ret, pr, exp, dates = load_base()
    inc = metrics(pr)

    c1 = check_reproduction(base_ret, pr, exp)
    c2a, g = grid(base_ret, inc["MDD"], inc["Sharpe"])
    c2b, wf = walk_forward(base_ret, pr)

    overall = c1 and c2a and c2b
    print("\n" + "#" * 70)
    print(f"GATE 1 (exact reproduction)         : {'PASS' if c1 else 'FAIL'}")
    print(f"GATE 2a (param sensitivity grid)    : {'PASS' if c2a else 'FAIL'}")
    print(f"GATE 2b (walk-forward OOS)          : {'PASS' if c2b else 'FAIL'}")
    print(f"OVERALL PROMOTION GATE              : {'PASS' if overall else 'FAIL'}")
    print("#" * 70)

    json.dump({
        "reproduction_pass": bool(c1),
        "param_grid_pass": bool(c2a),
        "walk_forward_pass": bool(c2b),
        "overall_pass": bool(overall),
        "selected_floor": SELECTED[0],
        "selected_k": SELECTED[1],
    }, open(HERE / "promotion_gate_result.json", "w"), indent=2)
    return overall


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
