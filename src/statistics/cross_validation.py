"""Purged / embargoed cross-validation and Combinatorial Purged CV (CPCV).

Implements leakage-aware cross-validation for financial ML, following the principles in
López de Prado, *Advances in Financial Machine Learning* (2018), ch. 7:

* **Purging** — remove training observations whose *label interval* overlaps any test-set label
  interval. Labels here are intervals ``[t, t1[t]]`` (e.g. a forward 5-day return occupies the 5
  trading days after the feature timestamp), so purging is driven by the actual intervals, never
  by a fixed row count.
* **Embargo** — additionally drop training observations in a short window immediately *after* each
  test block, to kill serial-correlation leakage that purging alone misses.
* **CPCV** — partition the timeline into ``N`` contiguous groups, choose ``k`` groups as the test
  set in every combination, apply purge+embargo, and aggregate the resulting out-of-sample folds.

All splitters are deterministic (no RNG). Indices are positional (0..n-1) over a time-ordered
sample; the caller supplies ``t1`` (label end times) aligned to that order.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterator

import numpy as np
import pandas as pd

__all__ = [
    "make_t1_from_horizon",
    "purge_train_indices",
    "embargo_train_indices",
    "PurgedKFold",
    "purged_kfold_splits",
    "cpcv_splits",
    "CPCVSplit",
]


# --------------------------------------------------------------------------- #
# Label intervals
# --------------------------------------------------------------------------- #
def make_t1_from_horizon(index: pd.Index, horizon: int) -> pd.Series:
    """Label-end index position for a fixed forward horizon.

    For observation at positional index ``i`` whose label is the forward ``horizon``-step return,
    the label occupies steps ``i+1 .. i+horizon`` and is realised at ``min(i+horizon, n-1)``.
    Returns a Series (index = ``index``) of label-end *positions*.
    """
    if horizon < 0:
        raise ValueError("horizon must be >= 0")
    n = len(index)
    ends = np.minimum(np.arange(n) + horizon, n - 1)
    return pd.Series(ends, index=index, name="t1")


def _as_positional_t1(t1: pd.Series | np.ndarray | None, n: int, horizon: int | None) -> np.ndarray:
    """Normalise the label-end specification to a positional int array of length n."""
    if t1 is None:
        if horizon is None:
            raise ValueError("provide either t1 or horizon")
        return np.minimum(np.arange(n) + int(horizon), n - 1)
    arr = np.asarray(t1.values if isinstance(t1, pd.Series) else t1)
    if arr.shape[0] != n:
        raise ValueError(f"t1 length {arr.shape[0]} != n {n}")
    # if t1 holds timestamps, map to positions by rank; if already positional ints, use as-is
    if np.issubdtype(arr.dtype, np.integer):
        return arr.astype(int)
    # timestamp-valued t1: convert each label-end time to the last position at/under it
    order = np.asarray(t1.index) if isinstance(t1, pd.Series) else np.arange(n)
    pos = np.searchsorted(np.sort(order), arr, side="right") - 1
    return np.clip(pos, 0, n - 1).astype(int)


# --------------------------------------------------------------------------- #
# Purge + embargo
# --------------------------------------------------------------------------- #
def purge_train_indices(train: np.ndarray, test: np.ndarray, t1: np.ndarray) -> np.ndarray:
    """Drop training obs whose label interval [i, t1[i]] overlaps the test label span.

    The test label span is ``[min(test), max(t1[test])]`` plus every test position itself. A
    training observation ``i`` is purged iff its interval ``[i, t1[i]]`` intersects the closed
    interval ``[test_start, test_end]`` where ``test_start = min(test)`` and
    ``test_end = max(max(test), max(t1[test]))``.
    """
    if len(test) == 0:
        return train
    test_start = int(np.min(test))
    test_end = int(max(np.max(test), np.max(t1[test])))
    keep = []
    for i in train:
        lab_start, lab_end = int(i), int(t1[i])
        overlaps = (lab_start <= test_end) and (lab_end >= test_start)
        if not overlaps:
            keep.append(i)
    return np.array(keep, dtype=int)


def embargo_train_indices(train: np.ndarray, test: np.ndarray, n: int, embargo: int) -> np.ndarray:
    """Drop training obs in the embargo window immediately AFTER each contiguous test block.

    ``embargo`` is a number of positions. Only training observations *after* a test block (higher
    positional index) are embargoed — the purge already handles the pre-test side via intervals.
    """
    if embargo <= 0 or len(test) == 0:
        return train
    test_sorted = np.sort(test)
    # contiguous test blocks
    blocks = np.split(test_sorted, np.where(np.diff(test_sorted) > 1)[0] + 1)
    banned = set()
    for b in blocks:
        hi = int(b[-1])
        banned.update(range(hi + 1, min(hi + 1 + embargo, n)))
    return np.array([i for i in train if i not in banned], dtype=int)


# --------------------------------------------------------------------------- #
# Purged K-Fold
# --------------------------------------------------------------------------- #
@dataclass
class _Fold:
    test: np.ndarray
    train: np.ndarray
    n_purged: int
    n_embargoed: int


class PurgedKFold:
    """K contiguous (chronological) test folds with purge + embargo applied to the train side."""

    def __init__(self, n_splits: int = 5, *, embargo: int = 0):
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        self.n_splits = n_splits
        self.embargo = int(embargo)

    def split(self, n: int, t1: np.ndarray | pd.Series | None = None,
              horizon: int | None = None) -> Iterator[_Fold]:
        t1p = _as_positional_t1(t1, n, horizon)
        bounds = np.linspace(0, n, self.n_splits + 1).astype(int)
        all_idx = np.arange(n)
        for f in range(self.n_splits):
            test = all_idx[bounds[f]:bounds[f + 1]]
            train0 = np.setdiff1d(all_idx, test, assume_unique=True)
            train1 = purge_train_indices(train0, test, t1p)
            train2 = embargo_train_indices(train1, test, n, self.embargo)
            yield _Fold(test=test, train=train2,
                        n_purged=len(train0) - len(train1),
                        n_embargoed=len(train1) - len(train2))


def purged_kfold_splits(n: int, n_splits: int, *, horizon: int | None = None,
                        t1: np.ndarray | pd.Series | None = None, embargo: int = 0) -> list[_Fold]:
    return list(PurgedKFold(n_splits, embargo=embargo).split(n, t1=t1, horizon=horizon))


# --------------------------------------------------------------------------- #
# Combinatorial Purged Cross-Validation
# --------------------------------------------------------------------------- #
@dataclass
class CPCVSplit:
    combo: tuple[int, ...]          # which groups are the test set
    test: np.ndarray
    train: np.ndarray
    n_purged: int
    n_embargoed: int


def cpcv_splits(n: int, n_groups: int, k_test: int, *, horizon: int | None = None,
                t1: np.ndarray | pd.Series | None = None, embargo: int = 0) -> list[CPCVSplit]:
    """Combinatorial Purged CV: all C(n_groups, k_test) test-group combinations, purged+embargoed.

    The timeline is split into ``n_groups`` contiguous equal-ish groups. Every combination of
    ``k_test`` groups becomes a test set (its groups may be non-adjacent); the rest is training,
    purged against each test block's label span and embargoed after each block.
    """
    if not (1 <= k_test < n_groups):
        raise ValueError("require 1 <= k_test < n_groups")
    t1p = _as_positional_t1(t1, n, horizon)
    bounds = np.linspace(0, n, n_groups + 1).astype(int)
    groups = [np.arange(bounds[g], bounds[g + 1]) for g in range(n_groups)]
    all_idx = np.arange(n)
    out = []
    for combo in combinations(range(n_groups), k_test):
        test = np.sort(np.concatenate([groups[g] for g in combo]))
        train0 = np.setdiff1d(all_idx, test, assume_unique=True)
        # purge against EACH contiguous test block separately (non-adjacent groups)
        test_blocks = [groups[g] for g in combo]
        train1 = train0
        for blk in test_blocks:
            train1 = purge_train_indices(train1, blk, t1p)
        train2 = embargo_train_indices(train1, test, n, embargo)
        out.append(CPCVSplit(combo=combo, test=test, train=train2,
                             n_purged=len(train0) - len(train1),
                             n_embargoed=len(train1) - len(train2)))
    return out
