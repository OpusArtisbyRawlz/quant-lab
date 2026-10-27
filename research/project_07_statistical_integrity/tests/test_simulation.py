"""
Tests for Project 07 — ``src.statistics.simulation`` (path-robustness / stress).

Deterministic: every test seeds its own ``np.random.default_rng``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.statistics import simulation as sim


# --------------------------------------------------------------------------- #
# Innovations
# --------------------------------------------------------------------------- #
def test_gaussian_innovations_shape_and_moments():
    rng = np.random.default_rng(0)
    z = sim.gaussian_innovations(2000, 500, rng)
    assert z.shape == (2000, 500)
    assert abs(z.mean()) < 0.02 and abs(z.std() - 1.0) < 0.02


def test_student_t_innovations_unit_variance():
    rng = np.random.default_rng(1)
    z = sim.student_t_innovations(6.0, 4000, 500, rng)
    assert abs(z.std() - 1.0) < 0.05          # standardised to unit variance
    assert stats.kurtosis(z.ravel(), fisher=False) > 3.5  # heavier than normal


def test_student_t_innovations_requires_nu_gt_2():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        sim.student_t_innovations(2.0, 10, 10, rng)


# --------------------------------------------------------------------------- #
# Parametric generators
# --------------------------------------------------------------------------- #
def test_simulate_gaussian_recovers_mu_sigma():
    rng = np.random.default_rng(2)
    paths = sim.simulate_gaussian(0.0004, 0.01, 2000, 500, rng)
    assert paths.shape == (500, 2000)
    assert abs(paths.mean() - 0.0004) < 5e-4
    assert abs(paths.std() - 0.01) < 5e-4


def test_simulate_gaussian_deterministic():
    a = sim.simulate_gaussian(0.0, 0.01, 100, 50, np.random.default_rng(7))
    b = sim.simulate_gaussian(0.0, 0.01, 100, 50, np.random.default_rng(7))
    assert np.array_equal(a, b)


def test_simulate_student_t_heavier_tails_than_gaussian():
    rng = np.random.default_rng(3)
    t_paths = sim.simulate_student_t(0.0, 0.01, 4.0, 3000, 200, rng)
    g_paths = sim.simulate_gaussian(0.0, 0.01, 3000, 200, np.random.default_rng(4))
    assert stats.kurtosis(t_paths.ravel(), fisher=False) > stats.kurtosis(g_paths.ravel(), fisher=False)


def test_simulate_garch_stationarity_guard():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        sim.simulate_garch(0.0, 1e-6, 0.2, 0.85, 100, 10, rng)   # alpha+beta > 1


def test_simulate_garch_produces_vol_clustering():
    rng = np.random.default_rng(5)
    paths = sim.simulate_garch(0.0, 2e-6, 0.08, 0.90, 3000, 50, rng, dist="normal")
    # squared-return autocorrelation should be clearly positive
    acf1 = np.mean([sim._acf(paths[i] ** 2, [1])[1] for i in range(paths.shape[0])])
    assert acf1 > 0.05


# --------------------------------------------------------------------------- #
# Block bootstrap paths (reuses bootstrap module)
# --------------------------------------------------------------------------- #
def test_block_bootstrap_paths_stay_within_support():
    rng = np.random.default_rng(6)
    returns = np.linspace(-0.05, 0.05, 500)
    paths = sim.block_bootstrap_paths(returns, 500, 100, 20.0, rng)
    assert paths.shape == (100, 500)
    assert paths.min() >= returns.min() - 1e-12
    assert paths.max() <= returns.max() + 1e-12   # cannot exceed historical support


def test_block_bootstrap_paths_deterministic():
    r = np.random.default_rng(0).normal(0, 0.01, 300)
    a = sim.block_bootstrap_paths(r, 300, 20, 10.0, np.random.default_rng(9))
    b = sim.block_bootstrap_paths(r, 300, 20, 10.0, np.random.default_rng(9))
    assert np.array_equal(a, b)


# --------------------------------------------------------------------------- #
# Fitting & selection
# --------------------------------------------------------------------------- #
def test_fit_student_t_recovers_low_nu_on_heavy_data():
    rng = np.random.default_rng(10)
    data = sim.student_t_innovations(5.0, 1, 20000, rng)[0] * 0.01
    fit = sim.fit_student_t(data)
    assert 3.0 < fit["nu"] < 8.0
    assert abs(fit["sigma"] - 0.01) < 2e-3


def test_fit_garch_recovers_persistence():
    rng = np.random.default_rng(11)
    true = sim.simulate_garch(0.0, 2e-6, 0.08, 0.90, 4000, 1, rng, dist="normal")[0]
    fit = sim.fit_garch(true, dist="normal")
    assert fit["converged"]
    assert 0.80 < fit["persistence"] < 0.999   # high persistence recovered


def test_fit_garch_standard_errors_optional_and_positive():
    rng = np.random.default_rng(11)
    r = sim.simulate_garch(0.0, 2e-6, 0.08, 0.90, 4000, 1, rng, dist="normal")[0]
    base = sim.fit_garch(r, dist="normal")
    assert "se_alpha" not in base                    # default output unchanged
    with_se = sim.fit_garch(r, dist="normal", return_se=True)
    assert with_se["alpha"] == base["alpha"]         # fit itself identical
    assert with_se["se_alpha"] > 0 and with_se["se_persistence"] > 0


def test_select_model_gaussian_for_gaussian():
    rng = np.random.default_rng(12)
    data = rng.normal(0.0003, 0.01, 5000)
    sel = sim.select_return_model(data)
    assert sel["model"] == "gaussian"


def test_select_model_escalates_for_garch_t_data():
    rng = np.random.default_rng(13)
    data = sim.simulate_garch(0.0, 2e-6, 0.10, 0.88, 5000, 1, rng, dist="t", nu=5.0)[0]
    sel = sim.select_return_model(data)
    assert sel["model"] in ("garch_t", "garch_normal")   # clustering detected → GARCH
    assert sel["diagnostics"]["vol_clustering"]


def test_simulate_from_model_roundtrip():
    rng = np.random.default_rng(14)
    data = rng.normal(0.0002, 0.012, 3000)
    sel = sim.select_return_model(data)
    paths = sim.simulate_from_model(sel, 3000, 100, rng)
    assert paths.shape == (100, 3000)


# --------------------------------------------------------------------------- #
# Path metrics
# --------------------------------------------------------------------------- #
def test_path_metrics_match_scalar_definitions():
    r = np.array([0.01, -0.02, 0.03, 0.00, -0.01])
    tw = sim.terminal_wealth(r)[0]
    assert abs(tw - np.prod(1 + r)) < 1e-12
    mdd = sim.path_max_drawdown(r)[0]
    equity = np.cumprod(1 + r)
    exp_mdd = (equity / np.maximum.accumulate(equity) - 1).min()
    assert abs(mdd - exp_mdd) < 1e-12


def test_path_max_drawdown_negative_and_bounded():
    rng = np.random.default_rng(15)
    paths = sim.simulate_gaussian(0.0, 0.02, 500, 200, rng)
    mdd = sim.path_max_drawdown(paths)
    assert (mdd <= 0).all() and (mdd >= -1).all()


def test_summarize_path_metrics_keys_and_probabilities():
    rng = np.random.default_rng(16)
    paths = sim.simulate_gaussian(0.0005, 0.01, 1000, 2000, rng)
    s = sim.summarize_path_metrics(paths)
    for key in ("median_cagr", "p5_cagr", "median_mdd", "p5_mdd",
                "prob_cagr_negative", "prob_mdd_below_20pct",
                "prob_mdd_below_30pct", "prob_mdd_below_40pct", "terminal_wealth_p50"):
        assert key in s
    assert 0.0 <= s["prob_cagr_negative"] <= 1.0
    assert s["p5_cagr"] <= s["median_cagr"]
    assert s["p5_mdd"] <= s["median_mdd"]


def test_time_under_water_fraction():
    r = np.array([0.05, -0.01, -0.01, 0.10])   # dips then recovers
    tuw = sim.path_time_under_water(r)[0]
    assert 0.0 < tuw < 1.0


# --------------------------------------------------------------------------- #
# Overlay-replay primitives (must match src.risk.drawdown exactly)
# --------------------------------------------------------------------------- #
def test_overlay_primitives_match_pandas_risk_module():
    from src.risk.drawdown import (compute_drawdown, drawdown_exposure_smooth,
                                   apply_exposure_to_return)
    rng = np.random.default_rng(100)
    r = rng.normal(0.0005, 0.01, 600)
    s = pd.Series(r)
    # drawdown
    dd_pd = compute_drawdown((1 + s).cumprod()).to_numpy()
    dd_np = sim.drawdown_paths(r)[0]
    assert np.allclose(dd_pd, dd_np, atol=1e-12)
    # smooth exposure
    e_pd = drawdown_exposure_smooth(pd.Series(dd_pd), 0.3, 5).to_numpy()
    e_np = sim.smooth_dd_exposure(dd_np, 0.3, 5)
    assert np.allclose(e_pd, e_np, atol=1e-12)
    # lagged application
    applied_pd = apply_exposure_to_return(s, pd.Series(e_pd)).to_numpy()
    applied_np = sim.apply_lagged_exposure(r, e_np[None, :])[0]
    assert np.allclose(applied_pd, applied_np, atol=1e-12)


def test_smooth_dd_exposure_bounds_and_guards():
    dd = np.array([0.0, -0.1, -0.5, -0.9])
    e = sim.smooth_dd_exposure(dd, 0.3, 5)
    assert e[0] == 1.0 and np.all(e >= 0.3 - 1e-12) and np.all(e <= 1.0 + 1e-12)
    assert e[1] > e[2] > e[3]           # monotonically de-risking into drawdown
    with pytest.raises(ValueError):
        sim.smooth_dd_exposure(dd, 1.5, 5)


def test_apply_lagged_exposure_no_lookahead():
    r = np.ones((1, 4)) * 0.1
    e = np.array([[0.5, 0.5, 0.5, 0.5]])
    out = sim.apply_lagged_exposure(r, e)[0]
    assert out[0] == 0.1               # first day uses exposure 1.0 (no look-ahead)
    assert np.allclose(out[1:], 0.05)  # subsequent days use lagged exposure


def test_path_max_underwater_days():
    # peak at t0, underwater t1..t3, recover t4 -> longest run 3
    r = np.array([[0.1, -0.02, -0.02, -0.02, 0.2]])
    assert sim.path_max_underwater_days(r)[0] == 3


# --------------------------------------------------------------------------- #
# Environment stress
# --------------------------------------------------------------------------- #
def test_environment_stress_preserves_strategy_mean():
    rng = np.random.default_rng(17)
    strat = rng.normal(0.001, 0.01, 1000)
    env = sim.simulate_gaussian(0.0, 0.03, 1000, 300, rng)   # higher-vol environment
    stressed = sim.environment_stress_paths(strat, env)
    assert abs(stressed.mean() - strat.mean()) < 1e-3          # strategy edge preserved
    assert stressed.std() > strat.std()                        # risk environment harsher


def test_regime_switching_stationary_fraction_and_stress():
    rng = np.random.default_rng(21)
    # baseline vs more-persistent high-vol: stress raises realised high fraction & vol
    base, hf_base = sim.regime_switching_paths(
        300, 3000, rng, p_enter_high=0.02, p_stay_high=0.80,
        sigma_calm=0.008, sigma_high=0.03, nu_calm=5.0, nu_high=5.0)
    stress, hf_stress = sim.regime_switching_paths(
        300, 3000, rng, p_enter_high=0.05, p_stay_high=0.92,
        sigma_calm=0.008, sigma_high=0.03, nu_calm=5.0, nu_high=5.0)
    assert hf_stress > hf_base
    # realised fraction near the analytic stationary fraction
    stat = 0.02 / (1 - 0.80 + 0.02)
    assert abs(hf_base - stat) < 0.03
    assert base.shape == (3000, 300)   # (n_paths, horizon)


def test_regime_switching_probability_guard():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        sim.regime_switching_paths(10, 10, rng, p_enter_high=1.5, p_stay_high=0.8,
                                   sigma_calm=0.01, sigma_high=0.03, nu_calm=5, nu_high=5)


# --------------------------------------------------------------------------- #
# Diagnostics & validation
# --------------------------------------------------------------------------- #
def test_return_diagnostics_keys_and_values():
    rng = np.random.default_rng(18)
    r = rng.normal(0.0004, 0.01, 3000)
    d = sim.return_diagnostics(r)
    assert abs(d["mean"] - 0.0004) < 5e-4
    assert 2.5 < d["kurtosis"] < 3.5      # near-normal Pearson kurtosis
    assert d["max_drawdown"] <= 0
    for key in ("acf_ret_lag1", "acf_abs_lag1", "acf_sq_lag1", "q01", "q99"):
        assert key in d


def test_synthetic_vs_real_flags_gaussian_missing_kurtosis():
    # Real data is heavy-tailed; a Gaussian generator should FAIL on kurtosis/tails.
    rng = np.random.default_rng(19)
    real = sim.student_t_innovations(3.5, 1, 4000, rng)[0] * 0.01
    gauss = sim.simulate_gaussian(real.mean(), real.std(ddof=1), 4000, 200, rng)
    cmp = sim.synthetic_vs_real(real, gauss)
    assert cmp["kurtosis"]["pass"] is False       # Gaussian cannot match heavy tails
    assert "kurtosis" in cmp["_material_failures"]


def test_synthetic_vs_real_gaussian_matches_gaussian():
    rng = np.random.default_rng(20)
    real = rng.normal(0.0003, 0.01, 4000)
    simd = sim.simulate_gaussian(real.mean(), real.std(ddof=1), 4000, 200, rng)
    cmp = sim.synthetic_vs_real(real, simd)
    assert cmp["kurtosis"]["pass"] and cmp["std"]["pass"]


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [[], [1.0, np.nan], [[1, 2], [3, 4]]])
def test_check_returns_rejects_bad(bad):
    with pytest.raises(ValueError):
        sim._check_returns(bad)


@pytest.mark.parametrize("h,n", [(0, 10), (10, 0), (-1, 5), (5, 2.5)])
def test_dim_guards(h, n):
    with pytest.raises(ValueError):
        sim._check_dims(h, n)
