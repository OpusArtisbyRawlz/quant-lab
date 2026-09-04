"""
M11 PR-2 — Bayesian measurement engine (stat_v1), pure-function tests.

Covers methodology §§1–2 and the §9 determinism/testability requirements that
can be proven without a database: posterior convergence, monotonicity, the
no-decay pooling limit, credible-interval correctness, deflation, decay, and
per-axis independence. The engine is a *measurement* — no promotion/retirement
decision is asserted here.
"""

from __future__ import annotations

import math

import pytest

from agents.research_intelligence.statistics import (
    StatPolicy, DEFAULT_POLICY, ExperimentEvidence,
    sharpe_se, deflated_sharpe, decay_weight,
    assess_hypothesis, credible_interval, pool_hypothesis,
    dersimonian_laird_tau2, _measure, _cell_posterior,
)


def _ev(i, s, **kw):
    kw.setdefault("T", 252); kw.setdefault("N", 252)
    return ExperimentEvidence(f"E{i}", net_sharpe=s, **kw)


# --- §1.1 likelihood ------------------------------------------------------

def test_sharpe_se_matches_lo_formula():
    S, T, N = 1.2, 500, 252
    s_per = S / math.sqrt(N)
    expected = math.sqrt((1 + 0.5 * s_per ** 2) / T) * math.sqrt(N)
    assert sharpe_se(S, T, N) == pytest.approx(expected)


def test_deflation_reduces_estimate_for_multiple_configs():
    se = 0.4
    assert deflated_sharpe(1.0, se, K=1) == 1.0          # no deflation
    d = deflated_sharpe(1.0, se, K=20)
    assert d < 1.0                                        # penalised for selection


# --- §6 decay -------------------------------------------------------------

def test_decay_weight_halves_each_half_life():
    assert decay_weight(0, 200) == 1.0
    assert decay_weight(200, 200) == pytest.approx(0.5)
    assert decay_weight(400, 200) == pytest.approx(0.25)
    assert decay_weight(9999, math.inf) == 1.0           # no-decay limit


# --- §1.3 posterior convergence + §9 no-decay limit -----------------------

def test_posterior_converges_toward_injected_effect():
    theta = 1.0
    few = assess_hypothesis([_ev(i, theta) for i in range(3)])
    many = assess_hypothesis([_ev(i, theta) for i in range(200)])
    # More evidence ⇒ posterior mean closer to θ and much tighter.
    assert abs(many.posterior_mean - theta) < abs(few.posterior_mean - theta)
    assert many.posterior_sd < few.posterior_sd
    assert many.quality.exceed_prob > 0.99


def test_no_decay_limit_equals_plain_conjugate_pooling():
    evs = [_ev(i, 0.8) for i in range(10)]
    p = StatPolicy(H=math.inf)
    st = assess_hypothesis(evs, p)
    # Manual single-cell Normal-Normal: φ_post = φ0 + Σφ_i, all se equal here.
    se = sharpe_se(0.8, 252, 252)
    phi = 1.0 / se ** 2
    phi_post = p.phi0 + 10 * phi
    mu = (p.phi0 * p.mu0 + 10 * phi * deflated_sharpe(0.8, se, 1)) / phi_post
    assert st.posterior_mean == pytest.approx(mu)
    assert st.posterior_sd == pytest.approx(math.sqrt(1.0 / phi_post))


def test_monotonicity_more_supporting_evidence_raises_pi_and_mu():
    base = assess_hypothesis([_ev(i, 1.0) for i in range(5)])
    more = assess_hypothesis([_ev(i, 1.0) for i in range(15)])
    assert more.posterior_mean >= base.posterior_mean
    assert more.quality.exceed_prob >= base.quality.exceed_prob


# --- §1.5 credible intervals ----------------------------------------------

def test_credible_interval_is_symmetric_about_mean():
    st = assess_hypothesis([_ev(i, 1.0) for i in range(20)])
    z = DEFAULT_POLICY.z_gamma
    assert st.ci_low == pytest.approx(st.posterior_mean - z * st.posterior_sd)
    assert st.ci_high == pytest.approx(st.posterior_mean + z * st.posterior_sd)
    assert st.ci_low < st.posterior_mean < st.ci_high


def test_wider_credible_level_widens_interval():
    evs = [_ev(i, 1.0) for i in range(10)]
    lo90, hi90 = credible_interval(1.0, 0.2, StatPolicy(gamma=0.10))
    lo99, hi99 = credible_interval(1.0, 0.2, StatPolicy(gamma=0.01))
    assert (hi99 - lo99) > (hi90 - lo90)


# --- §1.4 hierarchical pooling -------------------------------------------

def test_single_cell_tau2_is_zero():
    evs = [_ev(i, 1.0) for i in range(4)]
    measured = [_measure(e, DEFAULT_POLICY) for e in evs]
    cp = _cell_posterior(evs[0].cell, measured, DEFAULT_POLICY)
    assert dersimonian_laird_tau2([cp]) == 0.0


def test_pooling_shrinks_between_divergent_cells():
    # Two cells with opposite-signed effects → hypothesis mean between them.
    evs = ([_ev(i, 1.5, market="A") for i in range(5)]
           + [_ev(i + 100, -1.5, market="B") for i in range(5)])
    st = assess_hypothesis(evs)
    assert -1.5 < st.posterior_mean < 1.5
    assert st.tau2 > 0.0        # heterogeneity detected


# --- §2 axis independence -------------------------------------------------

def test_value_change_leaves_reproducibility_sign_untouched():
    # Same all-positive sign pattern, different magnitude → R.sign identical, V differs.
    low = assess_hypothesis([_ev(i, 0.6) for i in range(8)])
    high = assess_hypothesis([_ev(i, 1.8) for i in range(8)])
    assert low.reproducibility.sign == pytest.approx(high.reproducibility.sign)
    assert high.value.net_sharpe > low.value.net_sharpe


def test_reproducibility_sign_drops_with_conflicting_evidence():
    agree = assess_hypothesis([_ev(i, 1.0) for i in range(8)])
    conflict = assess_hypothesis(
        [_ev(i, 1.0) for i in range(4)] + [_ev(i + 50, -1.0) for i in range(4)]
    )
    assert conflict.reproducibility.sign < agree.reproducibility.sign


def test_generalisation_counts_passing_cells_across_contexts():
    evs = ([_ev(i, 1.5, market="IN", regime="low_vol") for i in range(4)]
           + [_ev(i + 100, 1.5, market="US", regime="high_vol") for i in range(4)])
    st = assess_hypothesis(evs)
    assert st.generalisation.count == 2          # both cells clear the bar
    assert st.generalisation.coverage > 0.0


# --- refutation / support bookkeeping (measurement only) ------------------

def test_negative_effect_yields_low_exceedance_high_lfdr():
    st = assess_hypothesis([_ev(i, -1.2) for i in range(20)])
    assert st.quality.exceed_prob < 0.05
    assert st.lfdr > 0.95
    assert st.n_contradicting > st.n_supporting


# --- §9 order independence ------------------------------------------------

def test_assessment_is_order_independent():
    evs = [_ev(i, 0.5 + 0.1 * (i % 3), delta=i) for i in range(12)]
    a = assess_hypothesis(evs)
    b = assess_hypothesis(list(reversed(evs)))
    assert a.posterior_mean == pytest.approx(b.posterior_mean)
    assert a.posterior_sd == pytest.approx(b.posterior_sd)
    assert a.quality.exceed_prob == pytest.approx(b.quality.exceed_prob)


def test_decay_downweights_older_evidence():
    # Old strong-positive, recent strong-negative. With decay, the posterior
    # leans more negative than with no decay (recent evidence dominates).
    evs = ([_ev(i, 2.0, delta=300) for i in range(5)]       # old
           + [_ev(i + 50, -2.0, delta=0) for i in range(5)])  # recent
    decayed = assess_hypothesis(evs, StatPolicy(H=100))
    undecayed = assess_hypothesis(evs, StatPolicy(H=math.inf))
    assert decayed.posterior_mean < undecayed.posterior_mean


def test_empty_evidence_raises():
    with pytest.raises(ValueError):
        assess_hypothesis([])
