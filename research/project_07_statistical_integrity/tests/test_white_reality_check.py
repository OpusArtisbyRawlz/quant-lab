"""
Regression tests for Project 07 — ``src.statistics.white_reality_check``.

``reality_check`` (White's Reality Check) is implemented and tested here.
``superior_predictive_ability`` (Hansen SPA) remains scaffold and stays skipped.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.statistics.white_reality_check import RealityCheckResult, reality_check


def test_reality_check_basic_result_shape():
    rng = np.random.default_rng(0)
    perf = pd.DataFrame(rng.normal(size=(300, 5)), columns=[f"s{i}" for i in range(5)])
    res = reality_check(perf, n_resamples=1000, expected_block_length=20.0, seed=1)
    assert isinstance(res, RealityCheckResult)
    assert res.test == "white_reality_check"
    assert res.n_strategies == 5 and res.n_resamples == 1000
    assert 0.0 <= res.p_value <= 1.0
    assert res.best_strategy in perf.columns


def test_reality_check_pure_noise_not_significant():
    # Zero-mean noise: the best strategy should not be flagged (large p-value).
    rng = np.random.default_rng(42)
    perf = pd.DataFrame(rng.normal(size=(500, 8)))
    res = reality_check(perf, n_resamples=2000, expected_block_length=10.0, seed=7)
    assert res.p_value > 0.10


def test_reality_check_strong_signal_is_significant():
    # One strategy with a clear positive mean edge -> reject the no-superiority null.
    rng = np.random.default_rng(3)
    perf = pd.DataFrame(rng.normal(scale=0.01, size=(500, 6)))
    perf[2] = perf[2] + 0.01          # persistent positive differential
    res = reality_check(perf, n_resamples=2000, expected_block_length=10.0, seed=9)
    assert res.best_strategy == 2
    assert res.p_value < 0.05


def test_reality_check_deterministic_for_fixed_seed():
    rng = np.random.default_rng(0)
    perf = pd.DataFrame(rng.normal(size=(200, 4)))
    a = reality_check(perf, n_resamples=1500, expected_block_length=20.0, seed=5)
    b = reality_check(perf, n_resamples=1500, expected_block_length=20.0, seed=5)
    assert a.p_value == b.p_value and a.best_statistic == b.best_statistic


def test_reality_check_addone_floor():
    # p-value can never be exactly 0 (add-one floor 1/(B+1)).
    rng = np.random.default_rng(1)
    perf = pd.DataFrame(rng.normal(scale=0.001, size=(400, 3)))
    perf[0] = perf[0] + 0.05          # overwhelming edge -> no null draw beats it
    res = reality_check(perf, n_resamples=1000, expected_block_length=10.0, seed=2)
    assert res.p_value >= 1.0 / (1000 + 1) - 1e-12
    assert res.p_value > 0.0


def test_reality_check_null_percentiles_ordered():
    rng = np.random.default_rng(0)
    perf = pd.DataFrame(rng.normal(size=(300, 5)))
    res = reality_check(perf, n_resamples=1000, expected_block_length=20.0, seed=1)
    assert np.isfinite(res.null_q95) and np.isfinite(res.null_q99)
    assert res.null_q99 >= res.null_q95


def test_reality_check_input_not_mutated():
    rng = np.random.default_rng(0)
    perf = pd.DataFrame(rng.normal(size=(100, 3)))
    before = perf.copy()
    reality_check(perf, n_resamples=200, expected_block_length=10.0, seed=0)
    pd.testing.assert_frame_equal(perf, before)


@pytest.mark.parametrize("bad_n", [0, -1, 2.5, True])
def test_reality_check_invalid_n_resamples_raises(bad_n):
    perf = pd.DataFrame(np.zeros((10, 3)))
    with pytest.raises(ValueError):
        reality_check(perf, n_resamples=bad_n)


def test_reality_check_empty_or_too_short_raises():
    with pytest.raises(ValueError):
        reality_check(pd.DataFrame(), n_resamples=100)
    with pytest.raises(ValueError):
        reality_check(pd.DataFrame(np.zeros((1, 3))), n_resamples=100)


def test_reality_check_non_finite_raises():
    perf = pd.DataFrame(np.ones((20, 3)))
    perf.iloc[0, 0] = np.nan
    with pytest.raises(ValueError):
        reality_check(perf, n_resamples=100)


@pytest.mark.skip(reason="Project 07 — superior_predictive_ability (Hansen SPA) not implemented yet")
def test_spa_not_implemented():
    raise NotImplementedError
