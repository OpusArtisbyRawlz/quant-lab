"""
Regression tests for Project 07 — ``src.statistics.deflated_sharpe``.

Only ``probabilistic_sharpe_ratio`` (PSR) is implemented so far, so only it is
tested here. ``deflated_sharpe_ratio`` / ``minimum_track_record_length`` remain
scaffold (``NotImplementedError``) and their tests stay skipped.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from src.statistics.deflated_sharpe import (
    DeflatedSharpeResult,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
)

# Deterministic sample used for the hand-computed case.
_DET = [0.01, -0.02, 0.03, 0.015, -0.005, 0.02, 0.005, -0.01]


def _psr_reference(returns, benchmark_sharpe=0.0):
    """Independent re-assembly of the AFML PSR formula (separate code path)."""
    s = pd.Series(returns).dropna()
    sr = s.mean() / s.std(ddof=1)
    g3 = s.skew()
    g4 = s.kurt() + 3.0
    T = len(s)
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr ** 2
    z = (sr - benchmark_sharpe) * np.sqrt(T - 1) / np.sqrt(denom)
    return float(norm.cdf(z))


def test_psr_in_unit_interval():
    psr = probabilistic_sharpe_ratio(pd.Series(_DET))
    assert 0.0 <= psr <= 1.0


def test_psr_benchmark_equals_observed_is_half():
    s = pd.Series(_DET)
    observed_sr = s.mean() / s.std(ddof=1)
    psr = probabilistic_sharpe_ratio(s, benchmark_sharpe=observed_sr)
    assert psr == pytest.approx(0.5, abs=1e-9)


def test_psr_higher_benchmark_lowers_psr():
    s = pd.Series(_DET)
    low = probabilistic_sharpe_ratio(s, benchmark_sharpe=0.0)
    high = probabilistic_sharpe_ratio(s, benchmark_sharpe=0.25)
    assert high < low


def test_psr_deterministic_hand_computed_case():
    s = pd.Series(_DET)
    psr = probabilistic_sharpe_ratio(s)
    # Independent re-assembly of the formula:
    assert psr == pytest.approx(_psr_reference(_DET), rel=0, abs=1e-12)
    # Hard-coded expected value (computed independently, T=8):
    assert psr == pytest.approx(0.805750380838, abs=1e-9)


def test_psr_fewer_than_four_observations_raises():
    for n in (0, 1, 2, 3):
        with pytest.raises(ValueError):
            probabilistic_sharpe_ratio(pd.Series([0.01] * n))


def test_psr_zero_variance_raises():
    with pytest.raises(ValueError):
        probabilistic_sharpe_ratio(pd.Series([0.01, 0.01, 0.01, 0.01, 0.01]))


def test_psr_non_finite_benchmark_raises():
    for bad in (np.nan, np.inf, -np.inf):
        with pytest.raises(ValueError):
            probabilistic_sharpe_ratio(pd.Series(_DET), benchmark_sharpe=bad)


def test_psr_non_finite_returns_raise():
    with pytest.raises(ValueError):
        probabilistic_sharpe_ratio(pd.Series([0.01, np.inf, 0.02, 0.03, -0.01]))


# --------------------------------------------------------------------------- #
# expected_max_sharpe
# --------------------------------------------------------------------------- #

def _ems_reference(n_trials, trial_sharpe_variance):
    """Independent re-assembly of the Bailey-Lopez de Prado E[max Sharpe] formula."""
    g, e = np.euler_gamma, np.e
    z = (1.0 - g) * norm.ppf(1.0 - 1.0 / n_trials) + g * norm.ppf(1.0 - 1.0 / (n_trials * e))
    return float(np.sqrt(trial_sharpe_variance) * z)


def test_ems_deterministic_hand_computed_case():
    # N=10, V=1.0 -> multiplier z (see AFML); independently recomputed + hard-coded.
    val = expected_max_sharpe(n_trials=10, trial_sharpe_variance=1.0)
    assert val == pytest.approx(_ems_reference(10, 1.0), rel=0, abs=1e-12)
    assert val == pytest.approx(1.574598301346, abs=1e-9)


def test_ems_increases_with_n_trials():
    vals = [expected_max_sharpe(n_trials=n, trial_sharpe_variance=1.0)
            for n in (2, 5, 10, 20, 50, 100)]
    assert all(b > a for a, b in zip(vals, vals[1:]))


def test_ems_increases_with_variance():
    vals = [expected_max_sharpe(n_trials=10, trial_sharpe_variance=v)
            for v in (1e-4, 1e-2, 1.0, 4.0)]
    assert all(b > a for a, b in zip(vals, vals[1:]))


def test_ems_zero_variance_is_zero():
    assert expected_max_sharpe(n_trials=10, trial_sharpe_variance=0.0) == 0.0


def test_ems_scales_with_sqrt_variance():
    # SR* is linear in sqrt(V): quadrupling V doubles SR*.
    base = expected_max_sharpe(n_trials=25, trial_sharpe_variance=1.0)
    quad = expected_max_sharpe(n_trials=25, trial_sharpe_variance=4.0)
    assert quad == pytest.approx(2.0 * base, rel=1e-12)


@pytest.mark.parametrize("bad_n", [1, 0, -5, 2.0, True])
def test_ems_n_trials_le_one_or_non_int_raises(bad_n):
    with pytest.raises(ValueError):
        expected_max_sharpe(n_trials=bad_n, trial_sharpe_variance=1.0)


@pytest.mark.parametrize("bad_v", [-1e-9, -1.0, np.nan, np.inf, -np.inf])
def test_ems_bad_variance_raises(bad_v):
    with pytest.raises(ValueError):
        expected_max_sharpe(n_trials=10, trial_sharpe_variance=bad_v)


# --------------------------------------------------------------------------- #
# deflated_sharpe_ratio
# --------------------------------------------------------------------------- #

def test_dsr_equals_psr_at_expected_max_benchmark():
    s = pd.Series(_DET)
    N, V = 10, 1e-4
    res = deflated_sharpe_ratio(s, n_trials=N, trial_sharpe_variance=V)
    sr_star = expected_max_sharpe(n_trials=N, trial_sharpe_variance=V)
    assert isinstance(res, DeflatedSharpeResult)
    assert res.expected_max_sharpe == sr_star
    assert res.deflated_probability == probabilistic_sharpe_ratio(s, benchmark_sharpe=sr_star)


def test_dsr_result_fields_populated():
    s = pd.Series(_DET)
    res = deflated_sharpe_ratio(s, n_trials=10, trial_sharpe_variance=1e-4)
    assert res.n_trials == 10
    assert res.n_observations == len(_DET)
    assert res.observed_sharpe == pytest.approx(s.mean() / s.std(ddof=1))
    assert res.skew == pytest.approx(s.skew())
    assert res.kurtosis == pytest.approx(s.kurt() + 3.0)
    assert 0.0 <= res.deflated_probability <= 1.0


def test_dsr_deterministic_hand_computed_case():
    res = deflated_sharpe_ratio(pd.Series(_DET), n_trials=10, trial_sharpe_variance=1e-4)
    assert res.deflated_probability == pytest.approx(0.7945594289033425, abs=1e-9)


def test_dsr_increasing_n_trials_lowers_dsr():
    s = pd.Series(_DET)
    vals = [deflated_sharpe_ratio(s, n_trials=n, trial_sharpe_variance=1e-4).deflated_probability
            for n in (2, 5, 10, 50, 100)]
    assert all(b < a for a, b in zip(vals, vals[1:]))


def test_dsr_increasing_variance_lowers_dsr():
    s = pd.Series(_DET)
    vals = [deflated_sharpe_ratio(s, n_trials=10, trial_sharpe_variance=v).deflated_probability
            for v in (1e-6, 1e-4, 1e-2, 1e-1)]
    assert all(b < a for a, b in zip(vals, vals[1:]))


def test_dsr_in_unit_interval():
    res = deflated_sharpe_ratio(pd.Series(_DET), n_trials=50, trial_sharpe_variance=1e-3)
    assert 0.0 <= res.deflated_probability <= 1.0


@pytest.mark.parametrize("bad_n", [1, 0, -3, 2.5, True])
def test_dsr_invalid_n_trials_raises(bad_n):
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(pd.Series(_DET), n_trials=bad_n, trial_sharpe_variance=1e-4)


@pytest.mark.parametrize("bad_v", [-1e-9, np.nan, np.inf])
def test_dsr_invalid_variance_raises(bad_v):
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(pd.Series(_DET), n_trials=10, trial_sharpe_variance=bad_v)


def test_dsr_invalid_returns_raise():
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(pd.Series([0.01, 0.02, 0.03]), n_trials=10, trial_sharpe_variance=1e-4)


# --------------------------------------------------------------------------- #
# minimum_track_record_length
# --------------------------------------------------------------------------- #

def _mintrl_reference(returns, benchmark_sharpe=0.0, confidence_level=0.95):
    """Independent re-assembly of the AFML minTRL formula."""
    s = pd.Series(returns).dropna()
    sr = s.mean() / s.std(ddof=1)
    g3 = s.skew()
    g4 = s.kurt() + 3.0
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr ** 2
    z = norm.ppf(confidence_level)
    return float(1.0 + denom * (z / (sr - benchmark_sharpe)) ** 2)


def test_mintrl_deterministic_hand_computed_case():
    val = minimum_track_record_length(pd.Series(_DET), benchmark_sharpe=0.0, confidence_level=0.95)
    assert val == pytest.approx(_mintrl_reference(_DET), rel=0, abs=1e-12)
    assert val == pytest.approx(26.467908274936, abs=1e-9)


def test_mintrl_roundtrip_with_psr():
    # At T = T_min, the PSR z-score reproduces the target confidence level.
    s = pd.Series(_DET)
    c = 0.95
    tmin = minimum_track_record_length(s, benchmark_sharpe=0.0, confidence_level=c)
    sr = s.mean() / s.std(ddof=1)
    g4 = s.kurt() + 3.0
    denom = 1.0 - s.skew() * sr + ((g4 - 1.0) / 4.0) * sr ** 2
    z = sr * np.sqrt(tmin - 1.0) / np.sqrt(denom)
    assert float(norm.cdf(z)) == pytest.approx(c, abs=1e-9)


def test_mintrl_increases_with_confidence():
    s = pd.Series(_DET)
    vals = [minimum_track_record_length(s, confidence_level=c) for c in (0.90, 0.95, 0.99)]
    assert vals[0] < vals[1] < vals[2]


def test_mintrl_increases_as_benchmark_approaches_observed():
    s = pd.Series(_DET)
    vals = [minimum_track_record_length(s, benchmark_sharpe=b) for b in (0.0, 0.1, 0.2, 0.3)]
    assert all(b > a for a, b in zip(vals, vals[1:]))


def test_mintrl_positive_and_finite():
    val = minimum_track_record_length(pd.Series(_DET))
    assert val > 0.0 and np.isfinite(val)


def test_mintrl_observed_le_benchmark_raises():
    s = pd.Series(_DET)
    sr = s.mean() / s.std(ddof=1)
    for b in (sr, sr + 0.1, 0.5):   # >= observed Sharpe (~0.339)
        with pytest.raises(ValueError):
            minimum_track_record_length(s, benchmark_sharpe=b)


@pytest.mark.parametrize("bad_c", [0.0, 1.0, -0.1, 1.5, 2])
def test_mintrl_confidence_out_of_range_raises(bad_c):
    with pytest.raises(ValueError):
        minimum_track_record_length(pd.Series(_DET), confidence_level=bad_c)


def test_mintrl_fewer_than_four_obs_raises():
    for n in (0, 1, 2, 3):
        with pytest.raises(ValueError):
            minimum_track_record_length(pd.Series([0.01] * n))


def test_mintrl_zero_variance_raises():
    with pytest.raises(ValueError):
        minimum_track_record_length(pd.Series([0.01, 0.01, 0.01, 0.01, 0.01]))


@pytest.mark.parametrize("bad_b", [np.nan, np.inf, -np.inf])
def test_mintrl_non_finite_benchmark_raises(bad_b):
    with pytest.raises(ValueError):
        minimum_track_record_length(pd.Series(_DET), benchmark_sharpe=bad_b)


def test_mintrl_non_finite_returns_raise():
    with pytest.raises(ValueError):
        minimum_track_record_length(pd.Series([0.01, np.inf, 0.02, 0.03, -0.01]))
