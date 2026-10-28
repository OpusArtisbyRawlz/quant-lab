"""
Regression tests for Project 07 — ``src.statistics.permutation``.

Scope: only ``permutation_indices`` is implemented so far, so only it is tested.
Tests are deterministic/structural (a permutation has exact, checkable
properties: length, integer dtype, bijection over ``[0, n-1]``).
"""
from __future__ import annotations

import numpy as np
import pytest

from src.statistics.permutation import (
    permutation_indices,
    permutation_metric,
    permutation_p_value,
    permutation_sample,
)


def _lag1_product_sum(sample: np.ndarray) -> float:
    """An order-DEPENDENT statistic (proxy for serial dependence): the sum of
    consecutive products. Unlike ``np.mean``, its value changes when the sample is
    permuted, so it is suitable for testing the permutation null distribution."""
    return float(np.sum(sample[:-1] * sample[1:]))


def test_output_length_equals_n():
    idx = permutation_indices(50, np.random.default_rng(0))
    assert idx.shape == (50,)
    assert len(idx) == 50


def test_dtype_is_integer():
    idx = permutation_indices(20, np.random.default_rng(0))
    assert np.issubdtype(idx.dtype, np.integer)


def test_indices_within_bounds():
    n = 100
    idx = permutation_indices(n, np.random.default_rng(123))
    assert idx.min() == 0
    assert idx.max() == n - 1


def test_every_index_appears_exactly_once():
    n = 200
    idx = permutation_indices(n, np.random.default_rng(7))
    # A permutation is a bijection over [0, n-1]: sorting recovers arange(n),
    # and there are exactly n unique values.
    assert np.array_equal(np.sort(idx), np.arange(n))
    assert len(np.unique(idx)) == n


def test_deterministic_for_fixed_seed():
    a = permutation_indices(200, np.random.default_rng(42))
    b = permutation_indices(200, np.random.default_rng(42))
    assert np.array_equal(a, b)


def test_different_seeds_generally_differ():
    a = permutation_indices(200, np.random.default_rng(1))
    b = permutation_indices(200, np.random.default_rng(2))
    assert not np.array_equal(a, b)


def test_n_one_works():
    idx = permutation_indices(1, np.random.default_rng(0))
    assert np.array_equal(idx, np.array([0]))


@pytest.mark.parametrize("bad_n", [0, -1, -100])
def test_invalid_n_raises(bad_n):
    with pytest.raises(ValueError):
        permutation_indices(bad_n, np.random.default_rng(0))


@pytest.mark.parametrize("bad_n", [1.0, 5.5, "10", None])
def test_non_integer_n_raises(bad_n):
    with pytest.raises(ValueError):
        permutation_indices(bad_n, np.random.default_rng(0))


@pytest.mark.parametrize("bad_n", [True, False])
def test_bool_n_raises(bad_n):
    # bool is a subclass of int and must be rejected explicitly.
    with pytest.raises(ValueError):
        permutation_indices(bad_n, np.random.default_rng(0))


# --------------------------------------------------------------------------- #
# permutation_sample
# --------------------------------------------------------------------------- #

def test_sample_length_preserved():
    values = np.linspace(-0.02, 0.02, 137)
    out = permutation_sample(values, np.random.default_rng(0))
    assert out.shape == values.shape
    assert len(out) == len(values)


def test_sample_is_1d():
    values = np.array([0.01, -0.01, 0.02, 0.0, -0.03])
    out = permutation_sample(values, np.random.default_rng(0))
    assert out.ndim == 1


def test_sample_every_value_appears_exactly_once():
    # Multiset is preserved: sorting the permuted sample recovers the sorted input.
    values = np.array([0.1, 0.2, 0.2, 0.3, 0.4, 0.4, 0.5])  # includes duplicates
    out = permutation_sample(values, np.random.default_rng(9))
    assert np.array_equal(np.sort(out), np.sort(values))


def test_sample_deterministic_for_fixed_seed():
    values = np.linspace(-0.05, 0.05, 200)
    a = permutation_sample(values, np.random.default_rng(42))
    b = permutation_sample(values, np.random.default_rng(42))
    assert np.array_equal(a, b)


def test_sample_different_seeds_generally_differ():
    values = np.linspace(-0.05, 0.05, 200)
    a = permutation_sample(values, np.random.default_rng(1))
    b = permutation_sample(values, np.random.default_rng(2))
    assert not np.array_equal(a, b)


def test_sample_input_unchanged():
    values = np.array([0.01, -0.01, 0.02, 0.0, -0.03])
    before = values.copy()
    _ = permutation_sample(values, np.random.default_rng(0))
    assert np.array_equal(values, before)


def test_sample_preserves_dtype():
    ints = np.array([1, 2, 3, 4, 5])
    out = permutation_sample(ints, np.random.default_rng(0))
    assert out.dtype == ints.dtype  # integer stays integer (no float cast)


def test_sample_uses_permutation_indices_logic():
    # sample == values[permutation_indices(n, same-seed rng)]
    values = np.linspace(-0.05, 0.05, 200)
    out = permutation_sample(values, np.random.default_rng(7))
    idx = permutation_indices(len(values), np.random.default_rng(7))
    assert np.array_equal(out, values[idx])


def test_sample_empty_input_raises():
    with pytest.raises(ValueError):
        permutation_sample(np.array([]), np.random.default_rng(0))


def test_sample_non_1d_input_raises():
    with pytest.raises(ValueError):
        permutation_sample(np.ones((4, 3)), np.random.default_rng(0))


def test_sample_non_numeric_input_raises():
    with pytest.raises(ValueError):
        permutation_sample(np.array(["a", "b", "c"]), np.random.default_rng(0))


# --------------------------------------------------------------------------- #
# permutation_metric (null-distribution engine)
# --------------------------------------------------------------------------- #

def test_metric_output_length_equals_n_permutations():
    values = np.linspace(-0.03, 0.03, 60)
    dist = permutation_metric(values, _lag1_product_sum, 500, np.random.default_rng(0))
    assert dist.shape == (500,)
    assert np.issubdtype(dist.dtype, np.floating)


def test_metric_deterministic_for_fixed_seed():
    values = np.linspace(-0.03, 0.03, 60)
    a = permutation_metric(values, _lag1_product_sum, 300, np.random.default_rng(42))
    b = permutation_metric(values, _lag1_product_sum, 300, np.random.default_rng(42))
    assert np.array_equal(a, b)


def test_metric_different_seeds_differ():
    # Uses an order-dependent metric so the null distribution actually varies.
    values = np.linspace(-0.03, 0.03, 60)
    a = permutation_metric(values, _lag1_product_sum, 300, np.random.default_rng(1))
    b = permutation_metric(values, _lag1_product_sum, 300, np.random.default_rng(2))
    assert not np.array_equal(a, b)


def test_metric_fn_called_exactly_n_permutations_times():
    values = np.array([0.01, -0.01, 0.02, 0.0, -0.03])
    calls = {"n": 0}

    def counting_metric(sample):
        calls["n"] += 1
        return _lag1_product_sum(sample)

    n_permutations = 250
    permutation_metric(values, counting_metric, n_permutations, np.random.default_rng(0))
    assert calls["n"] == n_permutations


def test_metric_input_unchanged():
    values = np.array([0.01, -0.01, 0.02, 0.0, -0.03])
    before = values.copy()
    permutation_metric(values, _lag1_product_sum, 200, np.random.default_rng(0))
    assert np.array_equal(values, before)


def test_metric_order_invariant_metric_is_constant():
    # An order-invariant metric (mean) has the same value for every permutation,
    # so the null distribution collapses to a constant — a deterministic proof
    # that metric_fn is applied to genuine permutations of the same multiset.
    values = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    dist = permutation_metric(values, np.mean, 100, np.random.default_rng(0))
    assert np.allclose(dist, np.mean(values))


@pytest.mark.parametrize("bad_n", [0, -1, -100])
def test_metric_invalid_n_permutations_raises(bad_n):
    values = np.array([0.01, -0.01, 0.02])
    with pytest.raises(ValueError):
        permutation_metric(values, _lag1_product_sum, bad_n, np.random.default_rng(0))


@pytest.mark.parametrize("bad_n", [True, False])
def test_metric_bool_n_permutations_raises(bad_n):
    values = np.array([0.01, -0.01, 0.02])
    with pytest.raises(ValueError):
        permutation_metric(values, _lag1_product_sum, bad_n, np.random.default_rng(0))


def test_metric_non_callable_raises():
    values = np.array([0.01, -0.01, 0.02])
    with pytest.raises(ValueError):
        permutation_metric(values, 123, 100, np.random.default_rng(0))  # type: ignore[arg-type]


def test_metric_invalid_values_raise():
    with pytest.raises(ValueError):
        permutation_metric(np.array([]), _lag1_product_sum, 100, np.random.default_rng(0))
    with pytest.raises(ValueError):
        permutation_metric(np.ones((3, 3)), _lag1_product_sum, 100, np.random.default_rng(0))
    with pytest.raises(ValueError):
        permutation_metric(
            np.array(["a", "b"]), _lag1_product_sum, 100, np.random.default_rng(0)
        )


# --------------------------------------------------------------------------- #
# permutation_p_value
# --------------------------------------------------------------------------- #

# Estimator under test (add-one / Davison–Hinkley):
#     p = (count(null >= observed) + 1) / (n + 1)

def test_pvalue_simple_known_example():
    null = np.array([1.0, 2.0, 3.0, 4.0, 5.0])  # n = 5
    # values >= 3 -> {3,4,5} -> count = 3 -> (3 + 1) / (5 + 1) = 4/6
    assert permutation_p_value(3.0, null) == pytest.approx(4 / 6)


def test_pvalue_observed_equal_to_a_distribution_value():
    null = np.array([1.0, 2.0, 3.0, 4.0, 5.0])  # n = 5
    # >= uses ties: values >= 5 -> {5} -> count = 1 -> (1 + 1) / (5 + 1) = 2/6
    assert permutation_p_value(5.0, null) == pytest.approx(2 / 6)


def test_pvalue_observed_larger_than_all():
    null = np.array([1.0, 2.0, 3.0, 4.0, 5.0])  # n = 5
    # count = 0, but add-one floors the p-value: (0 + 1) / (5 + 1) = 1/6, never 0.
    assert permutation_p_value(10.0, null) == pytest.approx(1 / 6)


def test_pvalue_smallest_attainable_is_one_over_n_plus_one():
    # The add-one estimator can never return 0; its floor is 1 / (n + 1).
    null = np.arange(1.0, 100.0)  # n = 99
    assert permutation_p_value(1e9, null) == pytest.approx(1 / (len(null) + 1))


def test_pvalue_observed_smaller_than_all():
    null = np.array([1.0, 2.0, 3.0, 4.0, 5.0])  # n = 5
    # count = 5 -> (5 + 1) / (5 + 1) = 6/6 = 1.0
    assert permutation_p_value(0.0, null) == pytest.approx(1.0)


def test_pvalue_all_ties_equals_one():
    null = np.full(7, 2.5)  # n = 7
    # every value == observed, and >= includes ties: count = 7 -> (7+1)/(7+1) = 1.0
    assert permutation_p_value(2.5, null) == pytest.approx(1.0)


def test_pvalue_in_unit_interval():
    rng = np.random.default_rng(0)
    null = rng.normal(size=1000)
    p = permutation_p_value(0.3, null)
    assert 0.0 <= p <= 1.0


def test_pvalue_deterministic():
    null = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    a = permutation_p_value(3.0, null)
    b = permutation_p_value(3.0, null)
    assert a == b


def test_pvalue_input_unchanged():
    null = np.array([3.0, 1.0, 4.0, 1.5, 9.0])
    before = null.copy()
    permutation_p_value(2.0, null)
    assert np.array_equal(null, before)


def test_pvalue_empty_distribution_raises():
    with pytest.raises(ValueError):
        permutation_p_value(1.0, np.array([]))


@pytest.mark.parametrize("bad_obs", [np.nan, np.inf, -np.inf])
def test_pvalue_non_finite_observed_raises(bad_obs):
    with pytest.raises(ValueError):
        permutation_p_value(bad_obs, np.array([1.0, 2.0, 3.0]))


@pytest.mark.parametrize("bad_obs", ["x", None])
def test_pvalue_non_numeric_observed_raises(bad_obs):
    with pytest.raises(ValueError):
        permutation_p_value(bad_obs, np.array([1.0, 2.0, 3.0]))


@pytest.mark.parametrize("bad_val", [np.nan, np.inf, -np.inf])
def test_pvalue_non_finite_distribution_raises(bad_val):
    with pytest.raises(ValueError):
        permutation_p_value(1.0, np.array([1.0, 2.0, bad_val]))


def test_pvalue_non_1d_distribution_raises():
    with pytest.raises(ValueError):
        permutation_p_value(1.0, np.ones((3, 3)))
