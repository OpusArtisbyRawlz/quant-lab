"""
M11 PR-3 — promotion policy (``promotion_v1``), pure-function tests.

Covers methodology §3.1: the promotion ladder is an **AND of per-axis gates**
(never a weighted sum), the recommendation is the highest contiguously-passed
tier, and the Production-Candidate gate is *capped* because its holdout (§5) and
BH-FDR (§7.2) inputs are not yet produced (unavailable ⇒ not satisfied, never
bypassed). No database, no RNG.
"""

from __future__ import annotations

import pytest

from agents.research_intelligence.promotion import (
    PromotionPolicy, DEFAULT_POLICY, PromotionInputs, recommend,
    CANDIDATE, PROMISING, VALIDATED, PRODUCTION_CANDIDATE, ARCHIVED,
    PROMOTION_LADDER, tier_of, FLAG_SUBPERIOD_INSTABILITY,
)


def _inputs(hid="H", **kw) -> PromotionInputs:
    """A hypothesis that satisfies every *numeric* gate up to and including
    Production Candidate; individual tests weaken one field at a time."""
    base = dict(
        hypothesis_id=hid,
        posterior_mean=0.9, posterior_sd=0.2, ci_low=0.6, ci_high=1.2, n_eff=12.0,
        q_exceed_prob=0.99, q_precision=0.9,
        r_sign=0.95, r_disp=0.8, r_replicas=0.9, replica_count=8,
        g_count=4, g_coverage=0.7,
        v_net_sharpe=0.9, v_ci_low=0.6, v_ci_high=1.2,
        has_unresolved_critical_flag=False,
        q_value=None, holdout_pass=None,
    )
    base.update(kw)
    return PromotionInputs(**base)


# --- ladder + ordinal -----------------------------------------------------

def test_ladder_order_and_ordinal():
    assert PROMOTION_LADDER == (CANDIDATE, PROMISING, VALIDATED, PRODUCTION_CANDIDATE)
    assert tier_of(CANDIDATE) == 0 < tier_of(PROMISING) < tier_of(VALIDATED)
    assert tier_of(VALIDATED) < tier_of(PRODUCTION_CANDIDATE) < tier_of(ARCHIVED)


# --- cap at Validated -----------------------------------------------------

def test_perfect_axes_are_capped_at_validated_without_holdout_and_fdr():
    # Every numeric ProdC gate passes, but holdout (§5) + FDR (§7.2) are absent.
    reco = recommend(_inputs())
    assert reco.recommended_stage == VALIDATED
    prodc = reco.gates[-1]
    assert prodc.stage == PRODUCTION_CANDIDATE
    assert prodc.passed is False
    # The block is *unavailability*, not a numeric failure.
    assert prodc.failures == ()
    assert set(prodc.unavailable) == {
        "bh_fdr_q_value (§7.2 not implemented)",
        "holdout_pass (§5 not implemented)",
    }


def test_production_candidate_reachable_once_holdout_and_fdr_supplied():
    # Proves the ProdC gate logic is correct and only *availability* caps PR-3:
    # feeding the two later-PR inputs lets a perfect hypothesis reach ProdC.
    reco = recommend(_inputs(q_value=0.01, holdout_pass=True))
    assert reco.recommended_stage == PRODUCTION_CANDIDATE
    assert reco.gates[-1].passed is True


def test_archived_is_never_auto_derived():
    for kw in (dict(), dict(q_value=0.001, holdout_pass=True)):
        reco = recommend(_inputs(**kw))
        assert reco.recommended_stage != ARCHIVED


# --- AND of per-axis gates (no weighted sum) ------------------------------

def test_single_weak_axis_blocks_promotion_no_compensation():
    # Strong Q/G/V but reproducibility sign collapses → cannot reach Validated,
    # and no amount of the other axes compensates (there is no sum).
    reco = recommend(_inputs(r_sign=0.1))
    assert reco.recommended_stage == PROMISING
    validated = reco.gates[1]
    assert validated.stage == VALIDATED and validated.passed is False
    assert any("rho_sign" in f for f in validated.failures)


def test_low_confidence_blocks_even_with_strong_value():
    reco = recommend(_inputs(q_exceed_prob=0.5, q_precision=0.9))
    assert reco.recommended_stage == CANDIDATE
    assert any("pi<" in f for f in reco.gates[0].failures)


def test_insufficient_replicas_blocks_validated():
    reco = recommend(_inputs(replica_count=2))   # < k_min = 3
    assert reco.recommended_stage == PROMISING
    assert any(f == "m<3" for f in reco.gates[1].failures)


def test_unresolved_critical_flag_blocks_validated():
    reco = recommend(_inputs(has_unresolved_critical_flag=True))
    assert reco.recommended_stage == PROMISING
    assert "unresolved_critical_robustness_flag" in reco.gates[1].failures


def test_negative_lower_credible_bound_blocks_validated():
    # π can be high while the 90% CI still straddles zero → not Validated.
    reco = recommend(_inputs(ci_low=-0.1))
    assert reco.recommended_stage == PROMISING
    assert any("ci_low<S0" in f for f in reco.gates[1].failures)


# --- Candidate floor + monotonicity ---------------------------------------

def test_weak_hypothesis_is_candidate():
    weak = _inputs(q_exceed_prob=0.6, q_precision=0.1, n_eff=1.0,
                   v_net_sharpe=0.05, ci_low=-0.3, replica_count=1, g_count=0)
    reco = recommend(weak)
    assert reco.recommended_stage == CANDIDATE
    assert reco.promotion_tier == 0


def test_promising_requires_all_four_of_its_conditions():
    # Exactly the Promising bar; dropping any one condition demotes to Candidate.
    ok = _inputs(q_exceed_prob=0.90, q_precision=0.30, v_net_sharpe=0.01,
                 n_eff=2.0, r_sign=0.0, g_count=0, replica_count=1)
    assert recommend(ok).recommended_stage == PROMISING
    assert recommend(_inputs(q_exceed_prob=0.90, q_precision=0.30, v_net_sharpe=0.0,
                             n_eff=2.0, r_sign=0.0, g_count=0,
                             replica_count=1)).recommended_stage == CANDIDATE  # mu_net not > 0


# --- versioning + determinism ---------------------------------------------

def test_method_is_promotion_v1():
    assert recommend(_inputs()).method == "promotion_v1"
    assert DEFAULT_POLICY.version == "promotion_v1"


def test_recommendation_is_a_pure_function():
    a = recommend(_inputs())
    b = recommend(_inputs())
    assert a == b


def test_custom_policy_thresholds_are_respected():
    strict = PromotionPolicy(pi_validated=0.999)
    reco = recommend(_inputs(q_exceed_prob=0.99), strict)
    assert reco.recommended_stage == PROMISING   # 0.99 < 0.999
    assert any("pi<0.999" in f for f in reco.gates[1].failures)


def test_gate_detail_is_serialisable_and_complete():
    detail = recommend(_inputs()).gate_detail()
    assert [g["stage"] for g in detail] == [
        PROMISING, VALIDATED, PRODUCTION_CANDIDATE]
    for g in detail:
        assert set(g) == {"stage", "passed", "failures", "unavailable"}
