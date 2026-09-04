"""
M11 PR-5 — FDR policy (``fdr_v1``), pure-function tests.

Covers methodology §7.1 (Bayesian FDR admission set), §7.2 (weighted-Stouffer
one-sided p-values + Benjamini–Hochberg / BY q-values). No database, no RNG — all
deterministic functions of the inputs.
"""

from __future__ import annotations

import math

import pytest

from agents.research_intelligence.fdr import (
    FdrPolicy, DEFAULT_POLICY, VARIANT_BH, VARIANT_BY,
    bayesian_fdr_admit, hypothesis_pvalue, benjamini_hochberg,
)
from agents.research_intelligence.statistics import ExperimentEvidence


def _ev(i, s, **kw):
    kw.setdefault("T", 2520); kw.setdefault("N", 252)
    return ExperimentEvidence(f"E{i}", net_sharpe=s, **kw)


# --- §7.1 Bayesian FDR admission ------------------------------------------

def test_admits_low_lfdr_prefix_under_alpha():
    lfdr = {"a": 0.001, "b": 0.01, "c": 0.02, "d": 0.60}
    admitted, avg = bayesian_fdr_admit(lfdr, DEFAULT_POLICY)  # alpha=0.10
    assert admitted == {"a", "b", "c"}         # d's inclusion would push avg > 0.10
    assert avg == pytest.approx((0.001 + 0.01 + 0.02) / 3)


def test_admits_nothing_when_all_lfdr_exceed_alpha():
    admitted, avg = bayesian_fdr_admit({"a": 0.4, "b": 0.5}, DEFAULT_POLICY)
    assert admitted == set()
    assert avg is None


def test_admission_is_a_prefix_and_deterministic():
    lfdr = {"z": 0.05, "y": 0.05, "x": 0.01}
    a = bayesian_fdr_admit(lfdr, DEFAULT_POLICY)
    b = bayesian_fdr_admit(dict(reversed(list(lfdr.items()))), DEFAULT_POLICY)
    assert a == b                              # order-independent
    assert a[0] == {"x", "y", "z"}             # mean 0.0367 ≤ 0.10


def test_alpha_controls_admission_size():
    lfdr = {"a": 0.05, "b": 0.15, "c": 0.60}
    strict = bayesian_fdr_admit(lfdr, FdrPolicy(alpha=0.05))[0]
    loose = bayesian_fdr_admit(lfdr, FdrPolicy(alpha=0.20))[0]
    assert strict == {"a"}                      # (0.05+0.15)/2 = 0.10 > 0.05
    assert loose == {"a", "b"}                  # 0.10 ≤ 0.20; adding c → 0.267 > 0.20


# --- §7.2 frequentist p-value ---------------------------------------------

def test_pvalue_small_for_strong_positive_evidence():
    p = hypothesis_pvalue([_ev(i, 1.5) for i in range(10)])
    assert p is not None and p < 0.001


def test_pvalue_near_half_for_null_effect():
    p = hypothesis_pvalue([_ev(i, 0.0) for i in range(8)])
    assert p == pytest.approx(0.5, abs=1e-6)


def test_pvalue_large_for_negative_effect():
    p = hypothesis_pvalue([_ev(i, -1.5) for i in range(10)])
    assert p is not None and p > 0.999


def test_pvalue_none_for_empty_evidence():
    assert hypothesis_pvalue([]) is None


def test_pvalue_is_order_independent():
    evs = [_ev(i, 0.4 + 0.1 * (i % 3)) for i in range(9)]
    assert hypothesis_pvalue(evs) == pytest.approx(hypothesis_pvalue(list(reversed(evs))))


# --- §7.2 Benjamini–Hochberg ----------------------------------------------

def test_bh_matches_hand_computed_example():
    # Classic BH: p = .01,.02,.03,.04,.05 over M=5.
    p = {"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.04, "e": 0.05}
    q = benjamini_hochberg(p, DEFAULT_POLICY)
    # q_(k) = min_{j>=k} M*p_(j)/j ; here every M*p/j = 0.05 → all q = 0.05.
    for v in q.values():
        assert v == pytest.approx(0.05)


def test_bh_is_monotone_and_clamped_to_one():
    p = {"a": 0.001, "b": 0.5, "c": 0.9}
    q = benjamini_hochberg(p, DEFAULT_POLICY)
    assert q["a"] <= q["b"] <= q["c"]
    assert all(v <= 1.0 for v in q.values())


def test_by_is_more_conservative_than_bh():
    p = {"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.04, "e": 0.05}
    q_bh = benjamini_hochberg(p, FdrPolicy(variant=VARIANT_BH))
    q_by = benjamini_hochberg(p, FdrPolicy(variant=VARIANT_BY))
    # BY multiplies by Σ1/j > 1, so every q is at least as large.
    for k in p:
        assert q_by[k] >= q_bh[k]
    assert q_by["a"] > q_bh["a"]


def test_bh_empty_population():
    assert benjamini_hochberg({}, DEFAULT_POLICY) == {}


def test_bh_ties_broken_deterministically():
    p = {"b": 0.02, "a": 0.02, "c": 0.02}
    q = benjamini_hochberg(p, DEFAULT_POLICY)
    assert set(q) == {"a", "b", "c"}
    assert all(v == pytest.approx(0.02 * 3 / 3) for v in q.values())


def test_policy_version_is_fdr_v1():
    assert DEFAULT_POLICY.version == "fdr_v1"
    assert DEFAULT_POLICY.alpha == 0.10 and DEFAULT_POLICY.q_max == 0.05
