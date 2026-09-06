"""
M11 PR-9 — failure-taxonomy policy (``failure_v1``), pure-function tests.

Covers the fixed reason-code taxonomy and its priority. No database, no RNG — a
pure function of the failure signals.
"""

from __future__ import annotations

from agents.research_intelligence.failure import (
    FailurePolicy, DEFAULT_POLICY, FailureSignals, classify,
    REASON_INSUFFICIENT_EVIDENCE, REASON_NO_EDGE, REASON_COST_FRAGILITY,
    REASON_SUBPERIOD_INSTABILITY, REASON_PARAMETER_FRAGILITY, REASON_REJECTED_OTHER,
)


def _sig(eid="E", decision=None, ns=1.0, T=2520, flags=()):
    return FailureSignals(eid, critic_decision=decision, net_sharpe=ns,
                          periods=T, robustness_flags=tuple(flags))


# --- non-failures ---------------------------------------------------------

def test_kept_positive_is_not_a_failure():
    r = classify(_sig(decision="keep", ns=1.4))
    assert r.is_failure is False and r.reason_code is None


def test_kept_but_flagged_positive_is_not_a_failure():
    # A robustness caveat on a kept, positive experiment is not a failure.
    r = classify(_sig(decision="keep", ns=1.2, flags=["cost_fragility"]))
    assert r.is_failure is False


# --- each reason ----------------------------------------------------------

def test_insufficient_evidence():
    r = classify(_sig(decision="reject", ns=1.0, T=60))
    assert r.is_failure and r.reason_code == REASON_INSUFFICIENT_EVIDENCE


def test_no_edge_from_rejection():
    r = classify(_sig(decision="reject", ns=-0.5, T=2520))
    assert r.reason_code == REASON_NO_EDGE


def test_no_edge_even_when_kept():
    # Net Sharpe ≤ S0 is a failure regardless of the critic decision.
    r = classify(_sig(decision="keep", ns=-0.3, T=2520))
    assert r.is_failure and r.reason_code == REASON_NO_EDGE


def test_cost_fragility():
    r = classify(_sig(decision="reject", ns=1.2, flags=["cost_fragility"]))
    assert r.reason_code == REASON_COST_FRAGILITY


def test_subperiod_instability():
    r = classify(_sig(decision="reject", ns=1.2, flags=["subperiod_instability"]))
    assert r.reason_code == REASON_SUBPERIOD_INSTABILITY


def test_parameter_fragility():
    r = classify(_sig(decision="reject", ns=1.2, flags=["parameter_fragility"]))
    assert r.reason_code == REASON_PARAMETER_FRAGILITY


def test_rejected_other_when_no_specific_signal():
    r = classify(_sig(decision="reject", ns=1.2, T=2520))
    assert r.reason_code == REASON_REJECTED_OTHER


# --- priority -------------------------------------------------------------

def test_insufficient_evidence_beats_no_edge():
    # Too few periods to even conclude "no edge".
    r = classify(_sig(decision="reject", ns=-0.5, T=60))
    assert r.reason_code == REASON_INSUFFICIENT_EVIDENCE


def test_no_edge_beats_flags():
    r = classify(_sig(decision="reject", ns=-0.5, T=2520, flags=["cost_fragility"]))
    assert r.reason_code == REASON_NO_EDGE


def test_flag_priority_cost_over_subperiod_over_parameter():
    r = classify(_sig(decision="reject", ns=1.2, T=2520,
                      flags=["parameter_fragility", "subperiod_instability", "cost_fragility"]))
    assert r.reason_code == REASON_COST_FRAGILITY


# --- config + determinism -------------------------------------------------

def test_min_periods_is_configurable():
    strict = FailurePolicy(min_periods=100)
    assert classify(_sig(decision="reject", ns=1.0, T=120)).reason_code == REASON_INSUFFICIENT_EVIDENCE
    assert classify(_sig(decision="reject", ns=1.0, T=120), strict).reason_code == REASON_REJECTED_OTHER


def test_missing_sample_size_skips_insufficient_check():
    r = classify(_sig(decision="reject", ns=1.2, T=None))
    assert r.reason_code == REASON_REJECTED_OTHER


def test_detail_carries_all_flags_sorted_and_is_pure():
    a = classify(_sig(decision="reject", ns=1.2, flags=["subperiod_instability", "cost_fragility"]))
    b = classify(_sig(decision="reject", ns=1.2, flags=["subperiod_instability", "cost_fragility"]))
    assert a == b
    assert a.detail["robustness_flags"] == ["cost_fragility", "subperiod_instability"]


def test_version_is_failure_v1():
    assert DEFAULT_POLICY.version == "failure_v1"
