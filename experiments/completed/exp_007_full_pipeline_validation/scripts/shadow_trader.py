"""Phase 8 — Shadow-trading harness (SIMULATION ONLY; no broker, no live orders).

Replays a FROZEN strategy against daily weight/return feeds and logs a hypothetical ledger:
per-day target weights, implied orders (Δweight·capital), modelled fills (price + slippage),
resulting positions, hypothetical P&L, cumulative equity, and the DEVIATION from the theoretical
backtest equity curve. In forward operation the only change is the feed: swap the replayed
historical weights for each day's freshly generated (frozen-code) weights. Nothing here connects
to a broker or market-data vendor.

Hard guards:
  * SIMULATION_ONLY is True and cannot be flipped by this file.
  * If any broker-like environment variable is present the harness REFUSES to run and exits.
Run (smoke test over preserved weights):
  PYTHONPATH=. venv/bin/python experiments/completed/exp_007_full_pipeline_validation/scripts/shadow_trader.py
"""
from __future__ import annotations
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd

SIMULATION_ONLY = True                      # invariant; this harness never places real orders
BROKER_ENV_HINTS = ("BROKER", "ALPACA", "IB_", "IBKR", "FIX_", "API_SECRET", "TRADING_KEY")
ROOT = Path("/Users/rawls/quant-lab")
E5 = ROOT / "experiments/completed/exp_005_risk_engine_final"
OUT = ROOT / "experiments/completed/exp_007_full_pipeline_validation"


def _refuse_if_broker_configured():
    hits = [k for k in os.environ if any(h in k.upper() for h in BROKER_ENV_HINTS)]
    if hits:
        sys.exit(f"REFUSED: broker-like env vars present {hits}. This harness is SIMULATION ONLY.")


@dataclass
class ShadowConfig:
    strategy_name: str
    code_commit: str
    frozen_params: str
    capital: float = 10_000_000.0
    slippage_bps: float = 2.0
    commission_bps: float = 1.0
    max_gross_exposure: float = 1.30        # hard cap; alert if a day's target exceeds it
    signal_schedule: str = "daily @ close (T); execute next open (T+1), 1-day lag already in weights"
    borrow_check: str = "require locate on every short; drop name + log if unavailable (stub)"
    financing: str = "charge fed-funds+50bps on gross>1.0 notional (stub rate feed)"
    stop_rule_dd: float = -0.25             # escalate if live shadow DD breaches this
    stop_rule_tracking_bps: float = 150.0   # escalate if |deviation| from theory exceeds this (ann.)


def run_shadow(weights_wide: pd.DataFrame, asset_returns: pd.DataFrame,
               theoretical_equity: pd.Series, cfg: ShadowConfig) -> pd.DataFrame:
    """weights_wide/asset_returns: index=Date, columns=Ticker. Returns the daily ledger."""
    assert SIMULATION_ONLY
    _refuse_if_broker_configured()
    dates = weights_wide.index
    prev_w = pd.Series(0.0, index=weights_wide.columns)
    equity = cfg.capital
    ledger = []
    for i, d in enumerate(dates):
        w = weights_wide.loc[d].fillna(0.0)
        gross = float(w.abs().sum())
        alert = "GROSS_CAP" if gross > cfg.max_gross_exposure + 1e-9 else ""
        dw = w - prev_w                                    # hypothetical orders (fraction of capital)
        turnover = float(dw.abs().sum())
        notional_traded = turnover * equity
        cost = notional_traded * (cfg.slippage_bps + cfg.commission_bps) / 1e4
        r = asset_returns.loc[d].reindex(w.index).fillna(0.0)
        gross_pnl = float((w * r).sum()) * equity          # position P&L (weights already T-1 lagged)
        net_pnl = gross_pnl - cost
        equity += net_pnl
        theo = float(theoretical_equity.iloc[i]) if i < len(theoretical_equity) else np.nan
        ledger.append({"date": str(pd.Timestamp(d).date()), "gross_exposure": round(gross, 4),
                       "n_long": int((w > 0).sum()), "n_short": int((w < 0).sum()),
                       "turnover": round(turnover, 4), "notional_traded": round(notional_traded, 2),
                       "cost": round(cost, 2), "gross_pnl": round(gross_pnl, 2),
                       "net_pnl": round(net_pnl, 2), "equity": round(equity, 2),
                       "theo_equity_scaled": round(theo * cfg.capital, 2) if theo == theo else np.nan,
                       "alert": alert})
        prev_w = w
    df = pd.DataFrame(ledger)
    # deviation vs theory (normalised equity)
    df["shadow_norm"] = df["equity"] / cfg.capital
    df["theo_norm"] = df["theo_equity_scaled"] / cfg.capital
    df["deviation"] = df["shadow_norm"] - df["theo_norm"]
    return df


def _smoke():
    """Replay the shipped V1 book over preserved weights as a self-test of the harness."""
    w = pd.read_csv(E5 / "final_daily_weights.csv", parse_dates=["Date"])
    W = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index()
    # per-asset returns are not stored cross-sectionally here; smoke test uses the portfolio identity:
    # approximate asset returns feed with a zero matrix is meaningless, so we instead validate plumbing
    # by feeding the stored portfolio return as a single synthetic asset.
    dep = pd.read_csv(E5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    dep.index = W.index
    synth_w = pd.DataFrame({"PORT": 1.0}, index=W.index)
    synth_r = pd.DataFrame({"PORT": dep["portfolio_return"].astype(float).values}, index=W.index)
    theo = (1 + dep["portfolio_return"].astype(float)).cumprod()
    cfg = ShadowConfig(strategy_name="V1_incumbent_shadow_smoke",
                       code_commit="9f0cef0", frozen_params="shipped dual-layer smooth-DD book")
    led = run_shadow(synth_w, synth_r, theo, cfg)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    led.to_csv(OUT / "data/shadow_smoke_ledger.csv", index=False)
    import json
    (OUT / "data/shadow_smoke_config.json").write_text(json.dumps(asdict(cfg), indent=2))
    print(f"SIMULATION_ONLY={SIMULATION_ONLY}; smoke ledger rows={len(led)}; "
          f"final shadow equity={led['equity'].iloc[-1]:,.0f}; "
          f"max |deviation vs theory|={led['deviation'].abs().max():.2e}")


if __name__ == "__main__":
    _smoke()
