"""
Golden-master regression test for the Project 06 deployment-validation layer.

Re-runs the full deployment validation on the reference strategy (Project 05
risk-engine final export) and asserts that the headline metrics — Sharpe, CAGR,
MDD, Calmar, turnover, participation and capacity — are unchanged versus the
committed golden baseline. Any future code change that shifts these numbers
beyond tolerance fails here.

Regenerate the baseline intentionally with:
    python research/project_06_deployment_validation/tests/deployment_reference.py
"""
from __future__ import annotations

import json

import pytest

from research.project_06_deployment_validation.tests.deployment_reference import (
    GOLDEN_PATH,
    compute_reference_metrics,
)

# Ratio metrics (Sharpe/CAGR/MDD/Calmar/turnover/participation) are dimensionless
# and reproduce to full float precision on a fixed input, so the tolerance is
# tight. Capacity-ceiling values are large dollar figures -> relative tolerance.
RTOL = 1e-9
ATOL = 1e-12
CAPITAL_RTOL = 1e-9


@pytest.fixture(scope="module")
def golden() -> dict:
    if not GOLDEN_PATH.exists():
        pytest.skip(
            f"golden baseline missing: {GOLDEN_PATH} "
            "(run deployment_reference.py to generate)"
        )
    return json.loads(GOLDEN_PATH.read_text())


@pytest.fixture(scope="module")
def current() -> dict:
    return compute_reference_metrics()


def _assert_block(cur: dict, gold: dict, keys, rtol=RTOL, atol=ATOL):
    for k in keys:
        assert k in cur, f"metric missing from current run: {k}"
        assert cur[k] == pytest.approx(gold[k], rel=rtol, abs=atol), (
            f"{k}: got {cur[k]!r}, expected {gold[k]!r}"
        )


def test_sample_shape(current, golden):
    assert current["n_days"] == golden["n_days"]
    assert current["n_assets"] == golden["n_assets"]


def test_gross_headline_metrics(current, golden):
    _assert_block(
        current["gross_0bps"], golden["gross_0bps"], ("Sharpe", "CAGR", "MDD", "Calmar")
    )


def test_net_10bps_metrics(current, golden):
    _assert_block(
        current["net_10bps"], golden["net_10bps"], ("Sharpe", "CAGR", "MDD", "Calmar")
    )


def test_turnover_profile(current, golden):
    _assert_block(current["turnover"], golden["turnover"], ("mean", "median", "max", "p95"))


def test_turnover_by_rebalance_frequency(current, golden):
    _assert_block(
        current["turnover_by_freq_mean"],
        golden["turnover_by_freq_mean"],
        tuple(golden["turnover_by_freq_mean"].keys()),
    )


def test_capacity_1m(current, golden):
    _assert_block(
        current["capacity_1m"],
        golden["capacity_1m"],
        ("Sharpe", "CAGR", "MDD", "Mean Participation"),
    )


def test_capacity_5m(current, golden):
    _assert_block(current["capacity_5m"], golden["capacity_5m"], ("Sharpe", "CAGR", "MDD"))


def test_capacity_ceiling(current, golden):
    _assert_block(
        current["capacity_ceiling_10pct"],
        golden["capacity_ceiling_10pct"],
        ("median_capital", "p05_capital", "min_capital"),
        rtol=CAPITAL_RTOL,
        atol=1.0,  # sub-dollar noise on ~$1e9 figures is irrelevant
    )
