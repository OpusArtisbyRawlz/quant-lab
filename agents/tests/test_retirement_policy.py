"""
M11 PR-6 — retirement policy (``retirement_v1``), pure-function tests.

Covers methodology §3.2 Retired-Refuted (the only state fired in PR-6) and the
modelled-but-deferred states. No database, no RNG — a pure function of the
current posterior (π_h, CI_high).
"""

from __future__ import annotations

import pytest

from agents.research_intelligence.retirement import (
    RetirementPolicy, DEFAULT_POLICY, RetirementInputs, evaluate_retirement,
    LIVE, RETIRED_REFUTED, DEFERRED_STATES,
    RETIRED_DECAYED, RETIRED_SATURATED, RETIRED_REDUNDANT,
)


def _in(hid="H", pi=0.5, ci_high=1.0, **kw):
    return RetirementInputs(hid, q_exceed_prob=pi, ci_high=ci_high, **kw)


# --- Retired-Refuted ------------------------------------------------------

def test_refuted_fires_when_both_conditions_hold():
    r = evaluate_retirement(_in(pi=0.02, ci_high=0.30))   # π≤0.05 and ci_high<0.5
    assert r.state == RETIRED_REFUTED
    assert r.retired is True and r.refuted is True
    assert r.reason is not None


def test_not_refuted_when_upside_remains():
    # Low π but the upper credible bound still clears the economic bar → not
    # affirmatively absent, so NOT refuted.
    r = evaluate_retirement(_in(pi=0.02, ci_high=0.60))    # ci_high ≥ S★
    assert r.state == LIVE and r.retired is False


def test_not_refuted_when_probability_too_high():
    # π above ε_ref even though ci_high < S★ → still some chance of an edge.
    r = evaluate_retirement(_in(pi=0.20, ci_high=0.30))
    assert r.state == LIVE and r.retired is False


def test_strong_hypothesis_is_live():
    r = evaluate_retirement(_in(pi=0.99, ci_high=1.5))
    assert r.state == LIVE
    assert r.reason is None and r.refuted is False


# --- boundaries (inclusive π, strict CI) ----------------------------------

def test_epsilon_ref_boundary_is_inclusive():
    assert evaluate_retirement(_in(pi=0.05, ci_high=0.30)).retired is True   # ≤ fires
    assert evaluate_retirement(_in(pi=0.0500001, ci_high=0.30)).retired is False


def test_s_star_boundary_is_strict():
    # ci_high exactly at S★ is NOT below it → not refuted.
    assert evaluate_retirement(_in(pi=0.01, ci_high=0.50)).retired is False
    assert evaluate_retirement(_in(pi=0.01, ci_high=0.4999)).retired is True


# --- deferred states ------------------------------------------------------

def test_deferred_states_are_modelled_but_never_fired():
    assert set(DEFERRED_STATES) == {RETIRED_DECAYED, RETIRED_SATURATED, RETIRED_REDUNDANT}
    detail = evaluate_retirement(_in(pi=0.99, ci_high=1.5)).detail()
    # Every deferred state is reported with its blocking reason, and none is the
    # assigned state.
    assert set(detail["deferred"]) == set(DEFERRED_STATES)
    for reason in detail["deferred"].values():
        assert isinstance(reason, str) and reason


# --- versioning + determinism ---------------------------------------------

def test_method_is_retirement_v1():
    assert evaluate_retirement(_in()).method == "retirement_v1"
    assert DEFAULT_POLICY.version == "retirement_v1"


def test_is_a_pure_function():
    assert evaluate_retirement(_in(pi=0.02, ci_high=0.3)) == \
        evaluate_retirement(_in(pi=0.02, ci_high=0.3))


def test_custom_policy_thresholds_respected():
    strict = RetirementPolicy(epsilon_ref=0.01)
    # π=0.03 refutes under default (≤0.05) but not under the stricter 0.01 bar.
    assert evaluate_retirement(_in(pi=0.03, ci_high=0.3)).retired is True
    assert evaluate_retirement(_in(pi=0.03, ci_high=0.3), strict).retired is False
