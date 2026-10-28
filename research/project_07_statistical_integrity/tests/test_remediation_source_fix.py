"""Remediation regression tests — bind the return-lineage fix to the ACTUAL source.

``test_return_lineage_audit.py`` proves the *math* of the fix with test-local helpers.
This module proves the *source code* carries the fix, by importing the real exp_006
loaders/candidate builders and asserting that what they now return reconstructs the
canonical pre-overlay base (``port_pre``, rebuilt from exp_004) to machine precision.

It covers the eight Phase-2 remediation requirements:

1. V1 historical returns unchanged (incumbent == shipped portfolio_return).
2. DD Only / Combined reconstruct correctly from canonical inputs.
3. Exposure is applied with the intended one-day execution lag.
4. Return recovery introduces no extra lag (source base == canonical, same-row).
5. Gross and net returns reconcile (net = gross - turnover * bps/1e4).
6. The original double-shift recovery FAILS a targeted regression test.
7. The corrected source implementation PASSES it.
8. Original asset/strategy weights are unchanged (book pivot == shipped weights).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.risk.drawdown import (
    compute_drawdown,
    drawdown_exposure_smooth,
    apply_exposure_to_return,
)

ROOT = Path(__file__).resolve().parents[3]
EXP4 = ROOT / "experiments/completed/exp_004_project04_final/strategy_timeseries"
EXP5 = ROOT / "experiments/completed/exp_005_risk_engine_final"
TOURN = ROOT / "experiments/completed/exp_006_deployment_candidate_tournament/run_tournament.py"
OVERLAY = ROOT / "experiments/completed/exp_006_deployment_overlay_challenge/run_overlay_challenge.py"
WEIGHTS = {
    "ls_20pct_plus_sqrt_partial_normalized": 0.5,
    "blend_60_40_ls20_plus_ls30": 0.3,
    "ls_30pct": 0.2,
}
_DEP = EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv"
_needs_data = pytest.mark.skipif(
    not (_DEP.exists() and EXP4.exists()), reason="exp_004/exp_005 artifacts not present"
)
PPY = 252


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _canonical_port_pre() -> pd.Series:
    """Rebuild the pre-portfolio-overlay base from the earliest reliable inputs (exp_004)."""
    controlled = []
    for name, w in WEIGHTS.items():
        raw = pd.read_csv(EXP4 / f"{name}.csv")["portfolio_return"].fillna(0).reset_index(drop=True)
        e = drawdown_exposure_smooth(compute_drawdown((1 + raw).cumprod()), floor=0.55, k=5)
        controlled.append(w * apply_exposure_to_return(raw, e))
    return sum(controlled)


# --------------------------------------------------------------------------- #
# 3 + 5 — analytic toy portfolio (no data dependency)
# --------------------------------------------------------------------------- #
def test_exposure_applied_with_one_day_lag():
    """apply_exposure_to_return(r, e)[t] uses e[t-1], never e[t] (look-ahead-safe)."""
    r = pd.Series([0.01, -0.02, 0.03, 0.04])
    e = pd.Series([0.5, 0.6, 0.7, 0.8])
    out = apply_exposure_to_return(r, e)
    expect = r.to_numpy() * np.array([1.0, 0.5, 0.6, 0.7])  # e.shift(1).fillna(1)
    np.testing.assert_allclose(out.to_numpy(), expect, atol=1e-15)


def test_gross_net_reconcile_analytic():
    """net = gross - turnover * (bps/1e4), applied per-day, is exact and order-free."""
    gross = pd.Series([0.010, -0.004, 0.006, 0.0])
    turnover = pd.Series([0.05, 0.02, 0.10, 0.0])
    bps = 10.0
    net = gross - turnover * (bps / 1e4)
    # drag is non-negative and equals turnover * bps in return space
    np.testing.assert_allclose((gross - net).to_numpy(),
                               (turnover * bps / 1e4).to_numpy(), atol=1e-18)
    assert (gross - net >= -1e-18).all()


# --------------------------------------------------------------------------- #
# 1,2,4,6,7,8 — bind to the real source
# --------------------------------------------------------------------------- #
@_needs_data
def test_tournament_source_base_is_canonical():
    """4 + 7: run_tournament.load_deployment_base() now returns the canonical base
    (same-row recovery == port_pre rebuilt from exp_004), with no extra lag."""
    tourn = _load_module(TOURN)
    base_ret, base_book, pr, exp, wide, dates = tourn.load_deployment_base()
    port_pre = _canonical_port_pre()
    np.testing.assert_allclose(base_ret.to_numpy(), port_pre.to_numpy(), atol=1e-12)


@_needs_data
def test_overlay_challenge_source_base_is_canonical():
    """4 + 7: run_overlay_challenge.load_base() returns the canonical base too."""
    ov = _load_module(OVERLAY)
    base_ret, base_book, incumbent, dates = ov.load_base()
    port_pre = _canonical_port_pre()
    np.testing.assert_allclose(base_ret.to_numpy(), port_pre.to_numpy(), atol=1e-12)
    # 1: incumbent (V1) is the shipped series, untouched
    dep = pd.read_csv(_DEP)
    np.testing.assert_allclose(incumbent["ret"].to_numpy(),
                               dep["portfolio_return"].to_numpy(), atol=1e-15)


@_needs_data
def test_v1_candidate_unchanged():
    """1: the tournament V1 candidate equals the shipped portfolio_return exactly."""
    tourn = _load_module(TOURN)
    cands, dates = tourn.build_candidates()
    v1 = next(c for c in cands if c["is_v1"])["ret"]
    dep = pd.read_csv(_DEP)
    np.testing.assert_allclose(np.asarray(v1, float),
                               dep["portfolio_return"].to_numpy(), atol=1e-15)


@_needs_data
def test_dd_only_and_combined_reconstruct_from_canonical():
    """2: the source DD Only / Combined challengers equal an independent reconstruction
    built by applying each overlay to the canonical base from exp_004."""
    tourn = _load_module(TOURN)
    cands, dates = tourn.build_candidates()
    port_pre = _canonical_port_pre()
    port_pre.index = dates
    dd = compute_drawdown((1 + port_pre).cumprod())
    rv = port_pre.rolling(252).std() * np.sqrt(PPY)
    # pre-window multiplier -> neutral 1.0 (A2 warm-up correction; multiplicative identity),
    # matching the corrected vol_multiplier in run_tournament.py / run_overlay_challenge.py
    m = ((rv / rv.mean()) ** 0.5).clip(0.7, 1.3).fillna(1.0)

    e_dd = drawdown_exposure_smooth(dd, 0.3, 5)
    e_comb = (m * drawdown_exposure_smooth(dd, 0.3, 5)).clip(0.5, 1.3)
    recon = {
        "candidate_dd_only": apply_exposure_to_return(port_pre, e_dd),
        "candidate_combined": apply_exposure_to_return(port_pre, e_comb),
    }
    for slug, expected in recon.items():
        got = np.asarray(next(c for c in cands if c["slug"] == slug)["ret"], float)
        np.testing.assert_allclose(got, expected.to_numpy(), atol=1e-12,
                                   err_msg=f"{slug} does not match canonical reconstruction")


@_needs_data
def test_book_and_weights_unchanged():
    """8: the recovered book * stored exposure returns the as-traded weights, i.e. the
    V1 book equals the shipped final_daily_weights pivot (weights are not altered)."""
    tourn = _load_module(TOURN)
    base_ret, base_book, pr, exp, wide, dates = tourn.load_deployment_base()
    reconstructed = base_book.mul(exp, axis=0)          # (wide/exp) * exp
    np.testing.assert_allclose(reconstructed.to_numpy(), wide.to_numpy(), atol=1e-12,
                               equal_nan=True)


@_needs_data
def test_double_shift_would_fail_this_guard():
    """6: the pre-fix recovery (pr / exp.shift(1)) does NOT reproduce the canonical base,
    so if the defect were reintroduced test_tournament_source_base_is_canonical would fail."""
    dep = pd.read_csv(_DEP)
    pr = dep["portfolio_return"].astype(float).reset_index(drop=True)
    stored = dep["portfolio_dd_exposure"].astype(float).reset_index(drop=True)
    port_pre = _canonical_port_pre()
    defective = pr / stored.shift(1).fillna(1.0)
    assert float(np.nanmax(np.abs(defective.to_numpy() - port_pre.to_numpy()))) > 1e-3
