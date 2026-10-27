"""Tests for purged/embargoed CV and CPCV (src/statistics/cross_validation.py).

Synthetic datasets with analytically known label overlaps verify: correct purging, embargo,
boundary handling, no future leakage, no over-removal, determinism, and irregular timestamps.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.statistics.cross_validation import (
    make_t1_from_horizon, purge_train_indices, embargo_train_indices,
    PurgedKFold, purged_kfold_splits, cpcv_splits,
)


def test_make_t1_horizon_caps_at_end():
    idx = pd.RangeIndex(10)
    t1 = make_t1_from_horizon(idx, horizon=3)
    assert list(t1.values) == [3, 4, 5, 6, 7, 8, 9, 9, 9, 9]


def test_purge_removes_exactly_the_overlapping_labels():
    # n=20, horizon=5; test = positions 10..14. A train obs i (label [i, i+5]) overlaps the test
    # label span [10, max(t1[10..14])=19] iff i+5 >= 10 and i <= 19 -> i in [5, 19].
    n, horizon = 20, 5
    t1 = make_t1_from_horizon(pd.RangeIndex(n), horizon).to_numpy()
    test = np.arange(10, 15)
    train = np.setdiff1d(np.arange(n), test)
    kept = purge_train_indices(train, test, t1)
    # pre-test survivors: i with i+5 < 10 -> i in [0,4]; post survivors: none (all i<=19 overlap via span to 19)
    assert set(kept) == {0, 1, 2, 3, 4}


def test_no_future_information_enters_training():
    n, horizon, k = 60, 5, 5
    folds = purged_kfold_splits(n, k, horizon=horizon)
    t1 = make_t1_from_horizon(pd.RangeIndex(n), horizon).to_numpy()
    for fold in folds:
        ts, te = int(fold.test.min()), int(max(fold.test.max(), t1[fold.test].max()))
        for i in fold.train:
            # no training label interval may overlap the test label span
            assert (int(i) > te) or (int(t1[i]) < ts)


def test_embargo_removes_only_post_test_window():
    n = 30
    test = np.arange(10, 15)                      # block 10..14
    train = np.setdiff1d(np.arange(n), test)
    kept = embargo_train_indices(train, test, n, embargo=3)
    assert {15, 16, 17}.isdisjoint(set(kept))     # embargoed
    assert 18 in kept and 9 in kept               # just outside / pre-test kept


def test_horizon_zero_purges_nothing_beyond_test():
    n, k = 40, 4
    folds = purged_kfold_splits(n, k, horizon=0, embargo=0)
    for fold in folds:
        # with no label overlap and no embargo, train == complement of test exactly
        assert len(fold.train) + len(fold.test) == n
        assert fold.n_purged == 0 and fold.n_embargoed == 0


def test_boundary_folds_first_and_last():
    n, k, horizon = 50, 5, 4
    folds = purged_kfold_splits(n, k, horizon=horizon)
    assert len(folds) == k
    assert folds[0].test.min() == 0                 # first fold starts at 0
    assert folds[-1].test.max() == n - 1            # last fold ends at n-1
    # union of test folds covers the whole sample, disjoint
    allt = np.sort(np.concatenate([f.test for f in folds]))
    assert np.array_equal(allt, np.arange(n))


def test_determinism():
    a = purged_kfold_splits(100, 5, horizon=5, embargo=2)
    b = purged_kfold_splits(100, 5, horizon=5, embargo=2)
    for x, y in zip(a, b):
        assert np.array_equal(x.train, y.train) and np.array_equal(x.test, y.test)


def test_irregular_timestamp_t1():
    # irregular calendar; label end = next business-ish gap. Provide positional t1 explicitly.
    n = 12
    t1 = np.array([2, 3, 5, 5, 7, 7, 8, 10, 10, 11, 11, 11])   # uneven label lengths
    test = np.arange(4, 7)                                       # positions 4,5,6
    train = np.setdiff1d(np.arange(n), test)
    kept = purge_train_indices(train, test, t1)
    ts, te = 4, int(max(6, t1[test].max()))                     # [4, 8]
    for i in kept:
        assert (i > te) or (t1[i] < ts)
    # obs 3 has label [3,5] -> overlaps [4,8] -> must be purged
    assert 3 not in kept


def test_purged_counts_reported():
    folds = purged_kfold_splits(60, 5, horizon=5, embargo=2)
    assert all(f.n_purged >= 0 and f.n_embargoed >= 0 for f in folds)
    # interior folds must purge something with a 5-step label
    interior = folds[2]
    assert interior.n_purged > 0


# --------------------------------------------------------------------------- #
# CPCV
# --------------------------------------------------------------------------- #
def test_cpcv_combination_count_and_sizes():
    n, N, k = 120, 6, 2
    splits = cpcv_splits(n, N, k, horizon=3, embargo=1)
    from math import comb
    assert len(splits) == comb(N, k)               # C(6,2)=15
    for s in splits:
        assert len(s.combo) == k
        assert set(s.test).isdisjoint(set(s.train))


def test_cpcv_no_leakage_across_nonadjacent_groups():
    n, N, k, horizon = 100, 5, 2, 4
    splits = cpcv_splits(n, N, k, horizon=horizon)
    t1 = make_t1_from_horizon(pd.RangeIndex(n), horizon).to_numpy()
    for s in splits:
        # every test group is a contiguous block; no train label may overlap any block's span
        for i in s.train:
            for g in s.combo:
                bounds = np.linspace(0, n, N + 1).astype(int)
                blk = np.arange(bounds[g], bounds[g + 1])
                bs, be = int(blk.min()), int(max(blk.max(), t1[blk].max()))
                assert (int(i) > be) or (int(t1[i]) < bs)


def test_cpcv_invalid_k():
    with pytest.raises(ValueError):
        cpcv_splits(100, 5, 5, horizon=1)          # k_test must be < n_groups
