"""
Regression tests for Project 07 — ``src.statistics.bootstrap``.

Scope: **only** ``stationary_bootstrap_indices`` is implemented so far, so only it
is tested here. The remaining bootstrap functions are still scaffold
(``NotImplementedError``) and are intentionally not exercised.

Tests favour deterministic, structural properties over statistical assertions;
the two "distributional" checks (iid-like behaviour at block length 1, and more
consecutive runs at larger block length) are written as robust inequalities on a
fixed seed rather than tight statistical claims.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.statistics.bootstrap import (
    bootstrap_confidence_interval,
    bootstrap_metric,
    paired_bootstrap_difference,
    stationary_bootstrap_indices,
    stationary_bootstrap_sample,
)


def _consecutive_wrap_fraction(idx: np.ndarray, n: int) -> float:
    """Fraction of steps where idx[i] == (idx[i-1] + 1) % n (a continued block)."""
    if len(idx) < 2:
        return 0.0
    continued = (idx[1:] == (idx[:-1] + 1) % n)
    return float(continued.mean())


def test_output_length_equals_n():
    idx = stationary_bootstrap_indices(50, 5.0, np.random.default_rng(0))
    assert idx.shape == (50,)
    assert len(idx) == 50


def test_dtype_is_integer():
    idx = stationary_bootstrap_indices(20, 3.0, np.random.default_rng(0))
    assert np.issubdtype(idx.dtype, np.integer)


def test_indices_within_bounds():
    n = 100
    idx = stationary_bootstrap_indices(n, 4.0, np.random.default_rng(123))
    assert idx.min() >= 0
    assert idx.max() <= n - 1


def test_deterministic_for_fixed_seed():
    a = stationary_bootstrap_indices(200, 6.0, np.random.default_rng(42))
    b = stationary_bootstrap_indices(200, 6.0, np.random.default_rng(42))
    assert np.array_equal(a, b)


def test_different_seeds_differ():
    a = stationary_bootstrap_indices(200, 6.0, np.random.default_rng(1))
    b = stationary_bootstrap_indices(200, 6.0, np.random.default_rng(2))
    assert not np.array_equal(a, b)


def test_circular_wrap_occurs():
    # With a long expected block length and a start forced near the end, the block
    # must wrap through 0. A large sample with long blocks makes an n-1 -> 0
    # transition overwhelmingly likely; assert at least one wrap is present.
    n = 50
    idx = stationary_bootstrap_indices(n, 25.0, np.random.default_rng(7))
    wrapped = np.any((idx[:-1] == n - 1) & (idx[1:] == 0))
    assert wrapped


def test_block_length_one_is_iid_like():
    # p = 1/1 = 1 -> every step starts a new block, so there should be (almost) no
    # continued runs. The only "continuations" would be coincidental random draws
    # landing on prev+1, which are rare.
    n = 2000
    idx = stationary_bootstrap_indices(n, 1.0, np.random.default_rng(0))
    frac = _consecutive_wrap_fraction(idx, n)
    assert frac < 0.05  # essentially iid: ~1/n coincidental matches expected


def test_larger_block_length_more_consecutive_runs():
    n = 2000
    short = stationary_bootstrap_indices(n, 2.0, np.random.default_rng(0))
    long = stationary_bootstrap_indices(n, 50.0, np.random.default_rng(0))
    assert _consecutive_wrap_fraction(long, n) > _consecutive_wrap_fraction(short, n)


@pytest.mark.parametrize("bad_n", [0, -1, -100])
def test_invalid_n_raises(bad_n):
    with pytest.raises(ValueError):
        stationary_bootstrap_indices(bad_n, 5.0, np.random.default_rng(0))


@pytest.mark.parametrize("bad_block", [0, -1.0, -5, float("inf"), float("nan")])
def test_invalid_block_length_raises(bad_block):
    with pytest.raises(ValueError):
        stationary_bootstrap_indices(10, bad_block, np.random.default_rng(0))


# --------------------------------------------------------------------------- #
# stationary_bootstrap_sample
# --------------------------------------------------------------------------- #

def test_sample_length_equals_input_length():
    returns = np.linspace(-0.02, 0.02, 137)
    sample = stationary_bootstrap_sample(returns, 5.0, np.random.default_rng(0))
    assert sample.shape == returns.shape
    assert len(sample) == len(returns)


def test_sample_is_1d():
    returns = np.array([0.01, -0.01, 0.02, 0.0, -0.03])
    sample = stationary_bootstrap_sample(returns, 3.0, np.random.default_rng(0))
    assert sample.ndim == 1


def test_input_is_not_mutated():
    returns = np.array([0.01, -0.01, 0.02, 0.0, -0.03])
    before = returns.copy()
    _ = stationary_bootstrap_sample(returns, 3.0, np.random.default_rng(0))
    assert np.array_equal(returns, before)


def test_all_values_come_from_original_sample():
    returns = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    sample = stationary_bootstrap_sample(returns, 4.0, np.random.default_rng(9))
    original = set(returns.tolist())
    assert all(v in original for v in sample.tolist())


def test_sample_deterministic_for_fixed_seed():
    returns = np.linspace(-0.05, 0.05, 200)
    a = stationary_bootstrap_sample(returns, 6.0, np.random.default_rng(42))
    b = stationary_bootstrap_sample(returns, 6.0, np.random.default_rng(42))
    assert np.array_equal(a, b)


def test_sample_uses_indices_logic():
    # The sample must equal returns[indices] where the indices are produced by the
    # existing generator with an identically-seeded rng (same draws -> same idx).
    returns = np.linspace(-0.05, 0.05, 200)
    sample = stationary_bootstrap_sample(returns, 6.0, np.random.default_rng(7))
    idx = stationary_bootstrap_indices(len(returns), 6.0, np.random.default_rng(7))
    assert np.array_equal(sample, returns[idx])


def test_empty_input_raises():
    with pytest.raises(ValueError):
        stationary_bootstrap_sample(np.array([]), 5.0, np.random.default_rng(0))


def test_non_1d_input_raises():
    with pytest.raises(ValueError):
        stationary_bootstrap_sample(
            np.ones((4, 3)), 5.0, np.random.default_rng(0)
        )


def test_non_numeric_input_raises():
    with pytest.raises(ValueError):
        stationary_bootstrap_sample(
            np.array(["a", "b", "c"]), 5.0, np.random.default_rng(0)
        )


def test_sample_preserves_float_values_from_int_input():
    returns = np.array([1, 2, 3, 4, 5])  # integer input
    sample = stationary_bootstrap_sample(returns, 3.0, np.random.default_rng(0))
    assert np.issubdtype(sample.dtype, np.floating)


# --------------------------------------------------------------------------- #
# bootstrap_metric (distribution engine)
# --------------------------------------------------------------------------- #

def test_metric_output_length_equals_n_bootstrap():
    returns = np.linspace(-0.03, 0.03, 120)
    dist = bootstrap_metric(returns, np.mean, 500, 5.0, np.random.default_rng(0))
    assert dist.shape == (500,)
    assert np.issubdtype(dist.dtype, np.floating)


def test_metric_deterministic_for_fixed_seed():
    returns = np.linspace(-0.03, 0.03, 120)
    a = bootstrap_metric(returns, np.mean, 300, 6.0, np.random.default_rng(42))
    b = bootstrap_metric(returns, np.mean, 300, 6.0, np.random.default_rng(42))
    assert np.array_equal(a, b)


def test_metric_different_seeds_differ():
    returns = np.linspace(-0.03, 0.03, 120)
    a = bootstrap_metric(returns, np.mean, 300, 6.0, np.random.default_rng(1))
    b = bootstrap_metric(returns, np.mean, 300, 6.0, np.random.default_rng(2))
    assert not np.array_equal(a, b)


def test_metric_fn_called_exactly_n_bootstrap_times():
    returns = np.array([0.01, -0.01, 0.02, 0.0, -0.03])
    calls = {"n": 0}

    def counting_metric(sample):
        calls["n"] += 1
        return float(np.mean(sample))

    n_bootstrap = 250
    bootstrap_metric(returns, counting_metric, n_bootstrap, 4.0, np.random.default_rng(0))
    assert calls["n"] == n_bootstrap


@pytest.mark.parametrize("bad_n", [0, -1, -100])
def test_metric_invalid_n_bootstrap_raises(bad_n):
    returns = np.array([0.01, -0.01, 0.02])
    with pytest.raises(ValueError):
        bootstrap_metric(returns, np.mean, bad_n, 4.0, np.random.default_rng(0))


def test_metric_non_callable_raises():
    returns = np.array([0.01, -0.01, 0.02])
    with pytest.raises(ValueError):
        bootstrap_metric(returns, 123, 100, 4.0, np.random.default_rng(0))  # type: ignore[arg-type]


def test_metric_input_returns_unchanged():
    returns = np.array([0.01, -0.01, 0.02, 0.0, -0.03])
    before = returns.copy()
    bootstrap_metric(returns, np.mean, 200, 4.0, np.random.default_rng(0))
    assert np.array_equal(returns, before)


def test_metric_values_are_plausible_for_known_metric():
    # Each resample of a constant series must have mean == the constant, so the
    # whole distribution collapses to that constant — a deterministic sanity check
    # that metric_fn is applied to the resampled data (no fake statistics).
    returns = np.full(50, 0.007)
    dist = bootstrap_metric(returns, np.mean, 100, 5.0, np.random.default_rng(0))
    assert np.allclose(dist, 0.007)


# --------------------------------------------------------------------------- #
# bootstrap_confidence_interval
# --------------------------------------------------------------------------- #

def test_ci_standard_error_matches_sample_std():
    dist = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    se, _, _ = bootstrap_confidence_interval(dist, 0.95)
    assert se == pytest.approx(np.std(dist, ddof=1))
    assert se == pytest.approx(1.5811388300841898)


def test_ci_95_percent_interval():
    dist = np.arange(0, 101, dtype=float)  # 0..100
    se, lo, hi = bootstrap_confidence_interval(dist, 0.95)
    # alpha=0.05 -> percentiles 2.5 and 97.5
    assert lo == pytest.approx(np.percentile(dist, 2.5))
    assert hi == pytest.approx(np.percentile(dist, 97.5))
    assert (lo, hi) == pytest.approx((2.5, 97.5))


def test_ci_80_percent_interval():
    dist = np.arange(0, 101, dtype=float)
    se, lo, hi = bootstrap_confidence_interval(dist, 0.80)
    # alpha=0.20 -> percentiles 10 and 90
    assert lo == pytest.approx(np.percentile(dist, 10.0))
    assert hi == pytest.approx(np.percentile(dist, 90.0))
    assert (lo, hi) == pytest.approx((10.0, 90.0))


def test_ci_returns_three_floats():
    dist = np.linspace(-1.0, 1.0, 500)
    result = bootstrap_confidence_interval(dist)
    assert isinstance(result, tuple) and len(result) == 3
    assert all(isinstance(x, float) for x in result)


@pytest.mark.parametrize("bad_level", [0.0, 1.0, -0.1, 1.5, 2, -3])
def test_ci_invalid_confidence_level_raises(bad_level):
    dist = np.array([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        bootstrap_confidence_interval(dist, bad_level)


def test_ci_empty_input_raises():
    with pytest.raises(ValueError):
        bootstrap_confidence_interval(np.array([]), 0.95)


def test_ci_non_1d_input_raises():
    with pytest.raises(ValueError):
        bootstrap_confidence_interval(np.ones((3, 3)), 0.95)


@pytest.mark.parametrize("bad_val", [np.nan, np.inf, -np.inf])
def test_ci_non_finite_input_raises(bad_val):
    dist = np.array([1.0, 2.0, bad_val, 4.0])
    with pytest.raises(ValueError):
        bootstrap_confidence_interval(dist, 0.95)


def test_ci_input_unchanged():
    dist = np.array([3.0, 1.0, 4.0, 1.5, 9.0, 2.6])
    before = dist.copy()
    bootstrap_confidence_interval(dist, 0.95)
    assert np.array_equal(dist, before)


# --------------------------------------------------------------------------- #
# paired_bootstrap_difference
# --------------------------------------------------------------------------- #

def test_paired_diff_output_length_and_dtype():
    a = np.linspace(-0.02, 0.03, 200)
    b = np.linspace(-0.03, 0.02, 200)
    d = paired_bootstrap_difference(a, b, np.mean, 500, 10.0, np.random.default_rng(0))
    assert d.shape == (500,)
    assert np.issubdtype(d.dtype, np.floating)


def test_paired_diff_identical_series_is_zero():
    # Same series + shared indices -> metric(a[idx]) - metric(a[idx]) == 0 every draw.
    a = np.linspace(-0.05, 0.05, 120)
    d = paired_bootstrap_difference(a, a.copy(), np.mean, 300, 20.0, np.random.default_rng(1))
    assert np.allclose(d, 0.0)


def test_paired_diff_deterministic_for_fixed_seed():
    a = np.linspace(-0.02, 0.03, 150); b = np.linspace(-0.03, 0.02, 150)
    x = paired_bootstrap_difference(a, b, np.mean, 400, 15.0, np.random.default_rng(42))
    y = paired_bootstrap_difference(a, b, np.mean, 400, 15.0, np.random.default_rng(42))
    assert np.array_equal(x, y)


def test_paired_diff_different_seeds_differ():
    a = np.linspace(-0.02, 0.03, 150); b = np.linspace(-0.03, 0.02, 150)
    x = paired_bootstrap_difference(a, b, np.mean, 400, 15.0, np.random.default_rng(1))
    y = paired_bootstrap_difference(a, b, np.mean, 400, 15.0, np.random.default_rng(2))
    assert not np.array_equal(x, y)


def test_paired_diff_inputs_unchanged():
    a = np.array([0.01, -0.01, 0.02, 0.0, -0.03]); b = np.array([0.0, 0.01, -0.02, 0.03, -0.01])
    a0, b0 = a.copy(), b.copy()
    paired_bootstrap_difference(a, b, np.mean, 100, 3.0, np.random.default_rng(0))
    assert np.array_equal(a, a0) and np.array_equal(b, b0)


def test_paired_diff_uses_shared_indices():
    # With shared indices, mean(a[idx]) - mean(b[idx]) == mean((a-b)[idx]); verify the
    # difference distribution equals bootstrapping the paired difference series directly.
    rng_seed = 7
    a = np.linspace(-0.02, 0.03, 100); b = np.linspace(-0.03, 0.02, 100)
    d_pair = paired_bootstrap_difference(a, b, np.mean, 200, 12.0, np.random.default_rng(rng_seed))
    diff = a - b
    d_direct = bootstrap_metric(diff, np.mean, 200, 12.0, np.random.default_rng(rng_seed))
    assert np.allclose(d_pair, d_direct, atol=1e-12)


def test_paired_diff_mismatched_length_raises():
    with pytest.raises(ValueError):
        paired_bootstrap_difference(np.zeros(10), np.zeros(9), np.mean, 100, 5.0,
                                    np.random.default_rng(0))


@pytest.mark.parametrize("bad_n", [0, -1, 2.5, True])
def test_paired_diff_invalid_n_raises(bad_n):
    a = np.zeros(10); b = np.zeros(10)
    with pytest.raises(ValueError):
        paired_bootstrap_difference(a, b, np.mean, bad_n, 5.0, np.random.default_rng(0))


def test_paired_diff_non_callable_metric_raises():
    a = np.zeros(10); b = np.zeros(10)
    with pytest.raises(ValueError):
        paired_bootstrap_difference(a, b, 123, 100, 5.0, np.random.default_rng(0))  # type: ignore[arg-type]


def test_paired_diff_empty_and_nonnumeric_raise():
    with pytest.raises(ValueError):
        paired_bootstrap_difference(np.array([]), np.array([]), np.mean, 100, 5.0,
                                    np.random.default_rng(0))
    with pytest.raises(ValueError):
        paired_bootstrap_difference(np.array(["a", "b"]), np.array(["c", "d"]), np.mean, 100, 5.0,
                                    np.random.default_rng(0))
