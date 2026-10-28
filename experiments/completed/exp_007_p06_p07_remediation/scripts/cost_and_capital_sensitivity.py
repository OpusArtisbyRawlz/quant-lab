"""Remediation Phase 3 — cost & capital sensitivity on the CORRECTED base.

Turnover and notional are derived from the actual position book (base_book * exposure),
not from exposure-scaled returns. Trading cost (commission+spread+slippage, blended bps on
one-way turnover) is supported by position data. Borrow/financing on the SHORT book is NOT in
the historical model, so it is handled with transparent bounded scenarios (no invented fees).

Costs are applied to GROSS returns only (never stacked on the already-net series) to avoid
double counting. Reports net Sharpe/CAGR across scenarios and the break-even incremental
trading cost at which each challenger's net-Sharpe edge over V1 vanishes.

Outputs: COST_AND_CAPITAL_SENSITIVITY.csv  (+ console summary)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
import sys
sys.path.insert(0, str(ROOT))

from src.utils.metrics import sharpe_ratio, annualized_return, max_drawdown
from src.risk.drawdown import compute_drawdown, drawdown_exposure_smooth, apply_exposure_to_return
from src.analysis.turnover import compute_turnover

TOURN = ROOT / "experiments/completed/exp_006_deployment_candidate_tournament/run_tournament.py"
EXP07 = ROOT / "experiments/completed/exp_007_candidate_net_validation"
REM = Path(__file__).resolve().parents[1]
PPY = 252
FILES = {"V1": "v1_daily_returns.csv", "DD Only": "dd_only_daily_returns.csv",
         "Combined DD+Vol": "combined_dd_vol_daily_returns.csv"}

TRADING_BPS = [0, 2, 5, 10, 20, 50]           # one-way, on book turnover (supported by positions)
BORROW_ANNUAL_BPS = [0, 25, 50, 100, 300]     # on mean short notional (ASSUMPTION — bounded scenarios)


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_tournament", TOURN)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    base_ret, base_book, pr, exp, wide, dates = m.load_deployment_base()
    base_ret.index = dates
    dd = compute_drawdown((1 + base_ret).cumprod())
    rv = base_ret.rolling(252).std() * np.sqrt(PPY)
    vmult = ((rv / rv.mean()) ** 0.5).clip(0.7, 1.3)
    e = {
        "V1": exp,                                                        # as-shipped stored exposure
        "DD Only": pd.Series(drawdown_exposure_smooth(dd, 0.3, 5), index=dates).fillna(1.0),
        "Combined DD+Vol": pd.Series((vmult * drawdown_exposure_smooth(dd, 0.3, 5)).clip(0.5, 1.3), index=dates).fillna(1.0),
    }
    books = {"V1": wide, "DD Only": base_book.mul(e["DD Only"], axis=0),
             "Combined DD+Vol": base_book.mul(e["Combined DD+Vol"], axis=0)}
    gross = {k: pd.read_csv(EXP07 / FILES[k], parse_dates=["date"]).set_index("date")["gross_return"] for k in FILES}
    return books, gross, dates


def _notional(book):
    long_n = book.clip(lower=0).sum(axis=1)
    short_n = (-book.clip(upper=0)).sum(axis=1)
    gross_n = book.abs().sum(axis=1)
    net_n = book.sum(axis=1)
    turn = compute_turnover(book).reindex(book.index).fillna(0.0)
    return dict(long=long_n, short=short_n, gross=gross_n, net=net_n, turnover=turn)


def _metrics(r):
    eq = (1 + r).cumprod()
    return dict(sharpe=float(sharpe_ratio(r, PPY)), cagr=float(annualized_return(r, PPY)),
                mdd=float(max_drawdown(eq)))


def net_series(gross, turnover, short_n, trade_bps, borrow_bps):
    trade_drag = turnover * (trade_bps / 1e4)
    borrow_drag = short_n * (borrow_bps / 1e4) / PPY      # annual bps on short notional, per day
    return gross - trade_drag - borrow_drag


def main():
    books, gross, dates = _load()
    notion = {k: _notional(books[k]) for k in books}

    rows = []
    # 1. descriptive notional / turnover (position-supported)
    print("=== position-book notional & turnover (corrected base) ===")
    for k in books:
        nd = notion[k]
        print(f"  {k:16} mean gross_notional={nd['gross'].mean():.3f} short={nd['short'].mean():.3f} "
              f"long={nd['long'].mean():.3f} net={nd['net'].mean():.3f} turnover={nd['turnover'].mean():.4f} "
              f"max_gross={nd['gross'].max():.3f}")
        rows.append({"scenario": "descriptive", "candidate": k, "trade_bps": np.nan, "borrow_bps": np.nan,
                     "mean_gross_notional": float(nd['gross'].mean()),
                     "mean_short_notional": float(nd['short'].mean()),
                     "mean_net_notional": float(nd['net'].mean()),
                     "mean_turnover": float(nd['turnover'].mean()),
                     "max_gross_notional": float(nd['gross'].max()),
                     "net_sharpe": np.nan, "net_cagr": np.nan, "net_mdd": np.nan})

    # 2. trading-cost sweep (borrow=0)
    print("\n=== trading-cost sweep (bps one-way on book turnover; borrow=0) ===")
    for bps in TRADING_BPS:
        line = []
        for k in books:
            r = net_series(gross[k], notion[k]["turnover"], notion[k]["short"], bps, 0)
            mm = _metrics(r); line.append(f"{k.split()[0]}:Sh{mm['sharpe']:.3f}/CAGR{mm['cagr']*100:.1f}%")
            rows.append({"scenario": "trading_sweep", "candidate": k, "trade_bps": bps, "borrow_bps": 0,
                         "mean_gross_notional": np.nan, "mean_short_notional": np.nan,
                         "mean_net_notional": np.nan, "mean_turnover": float(notion[k]["turnover"].mean()),
                         "max_gross_notional": np.nan,
                         "net_sharpe": mm["sharpe"], "net_cagr": mm["cagr"], "net_mdd": mm["mdd"]})
        print(f"  {bps:3d}bps  " + "  ".join(line))

    # 3. borrow/financing sweep (trading fixed at 10bps canonical)
    print("\n=== borrow sweep (annual bps on short notional; trading=10bps) ===")
    for bbps in BORROW_ANNUAL_BPS:
        line = []
        for k in books:
            r = net_series(gross[k], notion[k]["turnover"], notion[k]["short"], 10, bbps)
            mm = _metrics(r); line.append(f"{k.split()[0]}:Sh{mm['sharpe']:.3f}/CAGR{mm['cagr']*100:.1f}%")
            rows.append({"scenario": "borrow_sweep", "candidate": k, "trade_bps": 10, "borrow_bps": bbps,
                         "mean_gross_notional": np.nan, "mean_short_notional": float(notion[k]["short"].mean()),
                         "mean_net_notional": np.nan, "mean_turnover": float(notion[k]["turnover"].mean()),
                         "max_gross_notional": np.nan,
                         "net_sharpe": mm["sharpe"], "net_cagr": mm["cagr"], "net_mdd": mm["mdd"]})
        print(f"  {bbps:3d}bps/yr  " + "  ".join(line))

    # 4. break-even incremental trading cost erasing each challenger's net-Sharpe edge over V1
    print("\n=== break-even trading cost (challenger net-Sharpe edge vs V1 -> 0) ===")
    def dsharpe(bps, k):
        rk = net_series(gross[k], notion[k]["turnover"], notion[k]["short"], bps, 0)
        rv = net_series(gross["V1"], notion["V1"]["turnover"], notion["V1"]["short"], bps, 0)
        return _metrics(rk)["sharpe"] - _metrics(rv)["sharpe"]
    for k in ["DD Only", "Combined DD+Vol"]:
        grid = np.arange(0, 2001, 1)
        vals = np.array([dsharpe(b, k) for b in (0, 50, 100, 200, 500, 1000, 2000)])
        d0 = dsharpe(0, k)
        # scan for sign change
        be = None
        prev = dsharpe(0, k);
        for b in range(0, 3001, 5):
            cur = dsharpe(b, k)
            if np.sign(cur) != np.sign(prev) and prev != 0:
                be = b; break
            prev = cur
        note = (f"edge GROWS with cost (lower turnover than V1); no finite break-even up to 3000bps"
                if be is None else f"edge vanishes near {be} bps one-way")
        print(f"  {k:16} ΔSharpe@0bps={d0:+.3f}; {note}")
        rows.append({"scenario": "breakeven_trading", "candidate": k, "trade_bps": (be if be else np.nan),
                     "borrow_bps": 0, "mean_gross_notional": np.nan, "mean_short_notional": np.nan,
                     "mean_net_notional": np.nan, "mean_turnover": np.nan, "max_gross_notional": np.nan,
                     "net_sharpe": np.nan, "net_cagr": np.nan, "net_mdd": np.nan,
                     "dSharpe_vs_v1_at_0bps": d0, "breakeven_note": note})

    df = pd.DataFrame(rows)
    out = REM / "reports/COST_AND_CAPITAL_SENSITIVITY.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
