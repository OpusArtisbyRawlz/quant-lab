"""
Regression tests for Project 07 — ``src.statistics.significance``.

``bonferroni`` and ``benjamini_hochberg`` are implemented and tested here.
``holm`` and the Sharpe standard-error / t-stat helpers remain scaffold
(``NotImplementedError``) and their tests stay skipped.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.statistics.significance import (
    MultipleTestingResult,
    benjamini_hochberg,
    bonferroni,
)

_FAMILY_A = [0.0002, 0.0134, 0.0876, 0.8842]   # NB04 gross Family A (m=4)
_NET_FAMILY = [0.0002, 0.0110]                 # promoted net family (m=2)


def test_bonferroni_family_a_adjusted_values():
    res = bonferroni(np.array(_FAMILY_A), alpha=0.05)
    assert res.method == "bonferroni"
    np.testing.assert_allclose(res.adjusted_pvalues, [0.0008, 0.0536, 0.3504, 1.0], atol=1e-9)
    assert list(res.rejected) == [True, False, False, False]
    assert res.n_significant == 1


def test_bh_family_a_adjusted_values():
    res = benjamini_hochberg(np.array(_FAMILY_A), alpha=0.05)
    assert res.method == "benjamini_hochberg"
    np.testing.assert_allclose(res.adjusted_pvalues, [0.0008, 0.0268, 0.1168, 0.8842], atol=1e-9)
    assert list(res.rejected) == [True, True, False, False]
    assert res.n_significant == 2


def test_net_family_both_survive_bonferroni_and_bh():
    b = bonferroni(np.array(_NET_FAMILY), alpha=0.05)
    h = benjamini_hochberg(np.array(_NET_FAMILY), alpha=0.05)
    np.testing.assert_allclose(b.adjusted_pvalues, [0.0004, 0.0220], atol=1e-9)
    np.testing.assert_allclose(h.adjusted_pvalues, [0.0004, 0.0110], atol=1e-9)
    assert list(b.rejected) == [True, True]
    assert list(h.rejected) == [True, True]


def test_bh_adjusted_monotone_in_sorted_order():
    rng = np.random.default_rng(0)
    p = rng.uniform(size=25)
    res = benjamini_hochberg(p, alpha=0.1)
    adj_sorted = res.adjusted_pvalues[np.argsort(p)]
    assert np.all(np.diff(adj_sorted) >= -1e-12)   # non-decreasing


def test_output_order_matches_input_order():
    p = np.array(_FAMILY_A)
    perm = [3, 0, 2, 1]
    p_perm = p[perm]
    base = benjamini_hochberg(p, alpha=0.05).adjusted_pvalues
    permd = benjamini_hochberg(p_perm, alpha=0.05).adjusted_pvalues
    np.testing.assert_allclose(permd, base[perm], atol=1e-12)
    # same for bonferroni
    baseb = bonferroni(p, alpha=0.05).adjusted_pvalues
    permdb = bonferroni(p_perm, alpha=0.05).adjusted_pvalues
    np.testing.assert_allclose(permdb, baseb[perm], atol=1e-12)


@pytest.mark.parametrize("fn", [bonferroni, benjamini_hochberg])
def test_adjusted_pvalues_in_unit_interval(fn):
    rng = np.random.default_rng(1)
    p = rng.uniform(size=50)
    res = fn(p, alpha=0.05)
    assert res.adjusted_pvalues.min() >= 0.0 and res.adjusted_pvalues.max() <= 1.0
    assert isinstance(res, MultipleTestingResult)
    assert isinstance(res.adjusted_pvalues, np.ndarray) and isinstance(res.rejected, np.ndarray)


@pytest.mark.parametrize("fn", [bonferroni, benjamini_hochberg])
@pytest.mark.parametrize("bad_alpha", [0.0, 1.0, -0.1, 1.5, 2])
def test_invalid_alpha_raises(fn, bad_alpha):
    with pytest.raises(ValueError):
        fn(np.array([0.01, 0.2]), alpha=bad_alpha)


@pytest.mark.parametrize("fn", [bonferroni, benjamini_hochberg])
def test_empty_pvalues_raise(fn):
    with pytest.raises(ValueError):
        fn(np.array([]), alpha=0.05)


@pytest.mark.parametrize("fn", [bonferroni, benjamini_hochberg])
@pytest.mark.parametrize("bad_p", [[0.1, np.nan], [0.1, np.inf], [-0.01, 0.2], [0.2, 1.5]])
def test_non_finite_or_out_of_range_pvalues_raise(fn, bad_p):
    with pytest.raises(ValueError):
        fn(np.array(bad_p), alpha=0.05)


# --------------------------------------------------------------------------- #
# Still-scaffold (holm / Sharpe t-stat not implemented yet)
# --------------------------------------------------------------------------- #

@pytest.mark.skip(reason="Project 07 — holm not implemented yet")
def test_holm_step_down():
    raise NotImplementedError


@pytest.mark.skip(reason="Project 07 — sharpe_tstat not implemented yet")
def test_sharpe_tstat_sign():
    raise NotImplementedError
