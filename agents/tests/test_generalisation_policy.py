"""
M11 PR-10 — generalisation breakdown (§2.3), pure-function tests.

The single-source ``generalisation_breakdown`` that backs both the G-axis coverage
scalar and the ``generalisation_matrix`` projection. No database, no RNG.
"""

from __future__ import annotations

import pytest

from agents.research_intelligence.statistics import (
    ExperimentEvidence, DEFAULT_POLICY, _measure, _cell_posterior, _generalisation,
    generalisation_breakdown, GENERALISATION_DIMENSIONS,
)


def _ev(i, s, market="IN", universe="NIFTY", regime="all", ds="2020-01-01", de="2020-12-31"):
    return ExperimentEvidence(f"E{i}", net_sharpe=s, T=2520, N=252,
                              market=market, universe=universe, regime=regime,
                              bar_type="time", date_start=ds, date_end=de)


def _fold(evs, policy=DEFAULT_POLICY):
    measured = [_measure(e, policy) for e in evs]
    by: dict[tuple, list] = {}
    for md in measured:
        by.setdefault(md.cell, []).append(md)
    cells = [_cell_posterior(c, by[c], policy) for c in sorted(by)]
    return cells, measured


def _strong(market, regime, start, n=6, s=1.6):
    return [_ev(f"{market}-{regime}-{i}", s, market=market, regime=regime,
                ds=f"{2005+i}-01-01", de=f"{2005+i}-12-31") for i in range(start, start + n)]


# --- structure ------------------------------------------------------------

def test_breakdown_has_all_five_dimensions():
    cells, measured = _fold(_strong("IN", "all", 0))
    bd = generalisation_breakdown(cells, measured, DEFAULT_POLICY)
    assert [d.dimension for d in bd] == list(GENERALISATION_DIMENSIONS)


# --- coverage semantics ---------------------------------------------------

def test_market_low_coverage_when_one_market_fails():
    # Passes in 2 of 3 markets → market coverage = 2/3.
    evs = (_strong("IN", "all", 0) + _strong("US", "all", 0)
           + [_ev(f"JP-{i}", 0.02, market="JP") for i in range(6)])  # weak → fails
    cells, measured = _fold(evs)
    bd = {d.dimension: d for d in generalisation_breakdown(cells, measured, DEFAULT_POLICY)}
    assert bd["market"].available == 3
    assert bd["market"].passing == 2
    assert bd["market"].coverage == pytest.approx(2 / 3)


def test_coverage_matches_the_g_axis_scalar():
    evs = _strong("IN", "low_vol", 0) + _strong("US", "high_vol", 100)
    cells, measured = _fold(evs)
    bd = generalisation_breakdown(cells, measured, DEFAULT_POLICY)
    axis = _generalisation(cells, measured, DEFAULT_POLICY)
    # G^cov is exactly the mean of the per-dimension coverages (single source).
    assert axis.coverage == pytest.approx(sum(d.coverage for d in bd) / 5)
    assert axis.count == sum(
        1 for c in cells if c.exceed_prob(DEFAULT_POLICY) >= DEFAULT_POLICY.tau_pi)


def test_weak_cell_does_not_pass_tau_pi():
    # A single weak cell → no passing cells → zero coverage everywhere.
    cells, measured = _fold([_ev(i, 0.02) for i in range(6)])
    bd = generalisation_breakdown(cells, measured, DEFAULT_POLICY)
    assert all(d.passing == 0 and d.coverage == 0.0 for d in bd)


def test_available_counts_all_observed_values():
    evs = _strong("IN", "low_vol", 0) + _strong("US", "high_vol", 100)
    cells, measured = _fold(evs)
    bd = {d.dimension: d for d in generalisation_breakdown(cells, measured, DEFAULT_POLICY)}
    assert bd["market"].available == 2       # IN, US
    assert bd["regime"].available == 2       # low_vol, high_vol
    assert bd["universe"].available == 1


def test_breakdown_is_deterministic():
    evs = _strong("IN", "all", 0) + _strong("US", "all", 100)
    a = generalisation_breakdown(*_fold(evs), DEFAULT_POLICY)
    b = generalisation_breakdown(*_fold(list(reversed(evs))), DEFAULT_POLICY)
    assert [(d.dimension, d.passing, d.available) for d in a] == \
        [(d.dimension, d.passing, d.available) for d in b]
