"""Tests for PBO via CSCV (src/statistics/backtest_overfitting.py).

Known-answer synthetic cases: pure noise -> PBO ~ 0.5; a genuinely dominant strategy -> low PBO;
pure in-sample overfit (noise where IS winner is OOS-random) -> PBO ~ 0.5; determinism; logit math.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.statistics.backtest_overfitting import pbo_cscv, sharpe_objective, mean_objective


def test_combination_count_and_fields():
    rng = np.random.default_rng(0)
    M = rng.standard_normal((400, 8))
    res = pbo_cscv(M, S=10)
    from math import comb
    assert res.n_splits == comb(10, 5)
    assert res.n_strategies == 8 and res.S == 10
    assert 0.0 <= res.pbo <= 1.0
    assert res.logits.shape[0] == res.n_splits


def test_pure_noise_pbo_near_half():
    # N iid-noise strategies with no real edge: the IS winner is essentially random OOS -> PBO ~ 0.5
    rng = np.random.default_rng(42)
    M = rng.standard_normal((500, 12))
    res = pbo_cscv(M, S=12)
    assert 0.35 <= res.pbo <= 0.65


def test_dominant_strategy_low_pbo():
    # one strategy has a real, stationary positive mean; others are noise.
    rng = np.random.default_rng(7)
    M = rng.standard_normal((500, 10)) * 0.01
    M[:, 0] += 0.003                         # persistent edge in column 0
    res = pbo_cscv(M, S=12, objective=sharpe_objective)
    # the dominant strategy is picked IS and stays top OOS -> very low PBO
    assert res.pbo < 0.05
    assert (res.is_selected == 0).mean() > 0.9


def test_overfit_setup_high_pbo():
    # Construct IS-OOS anti-correlation: strategies that look best in the first half look worst in
    # the second half. Selecting the IS winner then reliably underperforms OOS -> PBO near 1.
    T, N = 400, 10
    half = T // 2
    rng = np.random.default_rng(3)
    M = rng.standard_normal((T, N)) * 0.001
    # give each strategy a first-half bonus that is exactly reversed in the second half
    bonus = np.linspace(-0.02, 0.02, N)
    M[:half, :] += bonus
    M[half:, :] -= bonus
    res = pbo_cscv(M, S=8, objective=mean_objective)
    assert res.pbo > 0.8


def test_determinism():
    rng = np.random.default_rng(1)
    M = rng.standard_normal((300, 6))
    r1 = pbo_cscv(M, S=10)
    r2 = pbo_cscv(M, S=10)
    assert r1.pbo == r2.pbo
    assert np.array_equal(r1.logits, r2.logits)


def test_logit_sign_matches_median_rule():
    # logit <= 0  <=>  relative rank w <= 0.5  <=>  selected strategy at/below OOS median
    rng = np.random.default_rng(9)
    M = rng.standard_normal((360, 8))
    res = pbo_cscv(M, S=10)
    below = res.oos_relative_ranks <= 0.5
    assert np.array_equal(below, res.logits <= 0.0)


def test_input_validation():
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 1)), S=8)          # need >= 2 strategies
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 4)), S=7)          # S must be even
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((4, 4)), S=8)            # T < S
