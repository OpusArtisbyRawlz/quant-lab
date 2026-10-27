"""Regression tests for the exp_006 return-lineage defect (research-integrity audit).

Root cause
----------
``exp_005`` stores, in ``final_weighted_multi_strategy_portfolio_dd.csv``:

    portfolio_return[t]       = port_pre[t] * portfolio_exp[t-1]     (overlay already applied, lagged)
    portfolio_dd_exposure[t]  = portfolio_exp[t-1]                   (the ALREADY-lagged exposure)

The correct inverse to recover the pre-overlay base is therefore a *same-row* divide::

    base[t] = portfolio_return[t] / portfolio_dd_exposure[t]   == port_pre[t]

Both ``exp_006_deployment_candidate_tournament`` and ``exp_006_deployment_overlay_challenge``
instead used ``base[t] = portfolio_return[t] / portfolio_dd_exposure[t-1]`` (a *second* shift),
injecting a spurious factor ``portfolio_exp[t-1] / portfolio_exp[t-2]`` on every day the exposure
moved. These tests FAIL under that double-shift recovery and PASS under the correct same-row one.
"""
from __future__ import annotations

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
WEIGHTS = {
    "ls_20pct_plus_sqrt_partial_normalized": 0.5,
    "blend_60_40_ls20_plus_ls30": 0.3,
    "ls_30pct": 0.2,
}
_DEP = EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv"
_needs_data = pytest.mark.skipif(
    not _DEP.exists(), reason="exp_005 deployment artifact not present"
)


# --------------------------------------------------------------------------- #
# Recovery conventions under test
# --------------------------------------------------------------------------- #
def recover_base_correct(pr: pd.Series, stored_exp: pd.Series) -> pd.Series:
    """Correct inverse: divide by the SAME-row stored (already-lagged) exposure."""
    return pr / stored_exp


def recover_base_double_shift(pr: pd.Series, stored_exp: pd.Series) -> pd.Series:
    """The exp_006 defect: divide by a SECOND shift of the stored exposure."""
    return pr / stored_exp.shift(1).fillna(1.0)


def _canonical_port_pre() -> pd.Series:
    """Rebuild the pre-portfolio-overlay base from the earliest reliable inputs (exp_004)."""
    controlled = []
    for name, w in WEIGHTS.items():
        raw = pd.read_csv(EXP4 / f"{name}.csv")["portfolio_return"].fillna(0).reset_index(drop=True)
        e = drawdown_exposure_smooth(compute_drawdown((1 + raw).cumprod()), floor=0.55, k=5)
        controlled.append(w * apply_exposure_to_return(raw, e))
    return sum(controlled)


# --------------------------------------------------------------------------- #
# Toy portfolio with an analytically known base and exposure
# --------------------------------------------------------------------------- #
def test_toy_double_shift_injects_known_spurious_factor():
    """On a toy book with a known base + lagged overlay, the correct recovery is exact and
    the double-shift recovery is off by exactly exp[t-1]/exp[t-2]."""
    base = pd.Series([0.01, -0.02, 0.03, -0.015, 0.02, 0.0, -0.03])
    raw_exp = pd.Series([1.0, 0.9, 0.8, 0.7, 0.85, 1.0, 1.0])  # decision-time exposure
    pr = apply_exposure_to_return(base, raw_exp)               # pr[t] = base[t]*raw_exp[t-1]
    stored = raw_exp.shift(1).fillna(1.0)                      # what exp_005 persists

    got_ok = recover_base_correct(pr, stored)
    np.testing.assert_allclose(got_ok.to_numpy(), base.to_numpy(), atol=1e-15)

    got_bad = recover_base_double_shift(pr, stored)
    expected_bad = base * (stored / stored.shift(1).fillna(1.0))
    np.testing.assert_allclose(got_bad.to_numpy(), expected_bad.to_numpy(), atol=1e-15)
    # and it is materially different from the true base wherever exposure moved
    assert np.nanmax(np.abs(got_bad.to_numpy() - base.to_numpy())) > 1e-3


@_needs_data
def test_shipped_return_equals_port_pre_times_stored_exposure():
    dep = pd.read_csv(_DEP)
    pr = dep["portfolio_return"].astype(float).reset_index(drop=True)
    stored = dep["portfolio_dd_exposure"].astype(float).reset_index(drop=True)
    port_pre = _canonical_port_pre()
    np.testing.assert_allclose((port_pre * stored).to_numpy(), pr.to_numpy(), atol=1e-12)


@_needs_data
def test_v1_reconstructs_from_project04_to_machine_precision():
    dep = pd.read_csv(_DEP)
    pr = dep["portfolio_return"].astype(float).reset_index(drop=True)
    port_pre = _canonical_port_pre()
    e = drawdown_exposure_smooth(compute_drawdown((1 + port_pre).cumprod()), floor=0.55, k=5)
    v1 = apply_exposure_to_return(port_pre, e)
    np.testing.assert_allclose(v1.to_numpy(), pr.to_numpy(), atol=1e-12)


@_needs_data
def test_correct_recovery_matches_canonical_base():
    dep = pd.read_csv(_DEP)
    pr = dep["portfolio_return"].astype(float).reset_index(drop=True)
    stored = dep["portfolio_dd_exposure"].astype(float).reset_index(drop=True)
    port_pre = _canonical_port_pre()
    recovered = recover_base_correct(pr, stored)
    np.testing.assert_allclose(recovered.to_numpy(), port_pre.to_numpy(), atol=1e-12)


@_needs_data
def test_double_shift_recovery_is_materially_wrong():
    """The shipped exp_006 recovery must NOT reproduce the canonical base — this is the
    regression guard: it documents the defect and fails if the bug is ever reintroduced
    as 'correct'."""
    dep = pd.read_csv(_DEP)
    pr = dep["portfolio_return"].astype(float).reset_index(drop=True)
    stored = dep["portfolio_dd_exposure"].astype(float).reset_index(drop=True)
    port_pre = _canonical_port_pre()
    defective = recover_base_double_shift(pr, stored)
    max_abs = float(np.nanmax(np.abs(defective.to_numpy() - port_pre.to_numpy())))
    assert max_abs > 1e-3, "double-shift recovery unexpectedly matched the canonical base"
