"""
M11 PR-7 — evidence-budget policy (``budget_v1``), pure-function tests.

Covers methodology §4.1 (EVOI), §4.2 (allocation with the hard a_max ceiling +
a_min floor, retired ⇒ 0), and §4.3 (the quota ``accept`` adapter). No database,
no RNG — deterministic functions of the inputs.
"""

from __future__ import annotations

import math

import pytest

from agents.research_intelligence.budget import (
    BudgetPolicy, DEFAULT_POLICY, evoi, nearest_gate, allocate, budget_admission,
)


# --- §4.1 EVOI ------------------------------------------------------------

def test_evoi_near_zero_for_saturated_tiny_sigma():
    # Tight posterior (σ→0): another experiment can't move a decision.
    assert evoi(mu=1.0, sigma=1e-6, mean_se2=0.0) < 1e-3


def test_evoi_near_zero_for_refuted_low_promise():
    # Strongly negative effect ⇒ π^prom = Pr(θ>S★) ≈ 0.
    assert evoi(mu=-2.0, sigma=0.3, mean_se2=0.05) < 1e-3


def test_evoi_high_for_uncertain_promising_near_threshold():
    strong_signal = evoi(mu=0.5, sigma=0.4, mean_se2=0.05)   # on S★, uncertain
    saturated = evoi(mu=0.5, sigma=1e-3, mean_se2=0.0)
    refuted = evoi(mu=-1.5, sigma=0.4, mean_se2=0.05)
    assert strong_signal > saturated
    assert strong_signal > refuted


def test_evoi_zero_when_sigma_nonpositive():
    assert evoi(mu=0.5, sigma=0.0, mean_se2=0.1) == 0.0


def test_nearest_gate_picks_closest_effect_threshold():
    assert nearest_gate(0.1) == 0.0        # nearer S0
    assert nearest_gate(0.45) == 0.5       # nearer S★
    assert nearest_gate(0.25) == 0.0       # tie → S0 (≤)


# --- §4.2 allocation: hard ceiling ----------------------------------------

def test_a_max_ceiling_never_exceeded_even_for_a_dominant_hypothesis():
    ev = {"A": 100.0, "B": 1.0, "C": 1.0, "D": 1.0, "E": 1.0}
    alloc = allocate(ev, set(ev), window=100, policy=DEFAULT_POLICY)
    assert all(a.a_frac <= DEFAULT_POLICY.a_max + 1e-9 for a in alloc.values())
    assert alloc["A"].capped is True
    assert alloc["A"].b_experiments == 25       # ⌊0.25 · 100⌋


def test_retired_hypothesis_gets_zero():
    ev = {"A": 5.0, "B": 5.0, "R": 9.0}
    alloc = allocate(ev, {"A", "B"}, window=40, policy=DEFAULT_POLICY)  # R not live
    assert alloc["R"].retired is True
    assert alloc["R"].a_frac == 0.0 and alloc["R"].b_experiments == 0


def test_evoi_proportionality_preserved_below_ceiling():
    ev = {"A": 3.0, "B": 1.0}
    alloc = allocate(ev, {"A", "B"}, window=100, policy=BudgetPolicy(a_max=0.9))
    assert alloc["A"].a_frac > alloc["B"].a_frac
    assert alloc["A"].share_raw == pytest.approx(0.75)


def test_a_min_floor_applied_to_tiny_evoi():
    ev = {"A": 100.0, "B": 0.0001}
    alloc = allocate(ev, {"A", "B"}, window=100, policy=DEFAULT_POLICY)
    assert alloc["B"].a_frac == pytest.approx(DEFAULT_POLICY.a_min)


def test_uniform_when_all_evoi_zero():
    ev = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
    alloc = allocate(ev, set(ev), window=20, policy=DEFAULT_POLICY)
    assert all(a.share_raw == pytest.approx(0.25) for a in alloc.values())


def test_down_normalises_when_a_min_floor_overflows():
    # Many hypotheses whose raw shares fall below a_min ⇒ floored, sum > 1 ⇒ scaled
    # down, and the ceiling still holds.
    ev = {f"H{i}": 1.0 for i in range(150)}
    alloc = allocate(ev, set(ev), window=300, policy=DEFAULT_POLICY)
    assert all(a.a_frac <= DEFAULT_POLICY.a_max + 1e-9 for a in alloc.values())
    assert sum(a.a_frac for a in alloc.values()) == pytest.approx(1.0, abs=1e-6)


def test_allocation_is_deterministic_and_order_independent():
    ev = {"A": 3.0, "B": 1.0, "C": 2.0}
    a = allocate(ev, {"A", "B", "C"}, 50)
    b = allocate(dict(reversed(list(ev.items()))), {"C", "B", "A"}, 50)
    assert {k: v.a_frac for k, v in a.items()} == {k: v.a_frac for k, v in b.items()}


def test_b_experiments_is_floor_of_share_times_window():
    ev = {"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0}
    alloc = allocate(ev, set(ev), window=10, policy=DEFAULT_POLICY)
    for a in alloc.values():
        assert a.b_experiments == int(math.floor(a.a_frac * 10))


# --- §4.3 quota `accept` adapter ------------------------------------------

def _cand(hid):
    return {"hid": hid}


def test_admission_enforces_per_hypothesis_budget():
    accept = budget_admission({"A": 2, "B": 0}, key_fn=lambda c: c["hid"])
    a = [_cand("A") for _ in range(5)]
    admitted = [c for c in a if accept(c)]
    assert len(admitted) == 2                    # only b_A = 2 admitted
    assert accept(_cand("B")) is False           # b_B = 0 admits none


def test_admission_counts_are_independent_per_hypothesis():
    accept = budget_admission({"A": 1, "B": 1}, key_fn=lambda c: c["hid"])
    assert accept(_cand("A")) is True
    assert accept(_cand("B")) is True            # B's budget independent of A's
    assert accept(_cand("A")) is False


def test_admission_passes_unmapped_candidates():
    accept = budget_admission({"A": 0}, key_fn=lambda c: c.get("hid"))
    assert accept({"other": 1}) is True          # no hid ⇒ budget doesn't govern


def test_policy_version_is_budget_v1():
    assert DEFAULT_POLICY.version == "budget_v1"
    assert DEFAULT_POLICY.a_max == 0.25
