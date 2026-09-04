"""
M11 PR-4 — holdout policy (``holdout_v1``), pure-function tests.

Covers methodology §5.1 (deterministic calendar partition) and §5.2 (the
two-posteriors-compared gate). No database, no RNG — the partition and the four
gate conditions are pure, deterministic functions.
"""

from __future__ import annotations

import pytest

from agents.research_intelligence.holdout import (
    HoldoutPolicy, DEFAULT_POLICY, partition_is_oos, evaluate_holdout,
)


def _row(eid, ds, de, market="IN", universe="NIFTY"):
    return {"experiment_id": eid, "date_start": ds, "date_end": de,
            "market": market, "universe": universe}


# --- §5.1 calendar partition ----------------------------------------------

def test_partition_splits_recent_fraction_as_oos():
    # 10 one-year windows 2010..2019; π=0.30 ⇒ boundary at 70% of the span.
    rows = [_row(f"E{i}", f"20{10+i:02d}-01-01", f"20{10+i:02d}-12-31") for i in range(10)]
    is_rows, oos_rows = partition_is_oos(rows, DEFAULT_POLICY)
    is_ids = {r["experiment_id"] for r in is_rows}
    oos_ids = {r["experiment_id"] for r in oos_rows}
    # Most-recent windows are OOS; earliest are IS; partition is a clean split.
    assert oos_ids and is_ids
    assert is_ids | oos_ids == {f"E{i}" for i in range(10)}
    assert is_ids & oos_ids == set()
    # The latest experiment is OOS, the earliest is IS.
    assert "E9" in oos_ids and "E0" in is_ids


def test_partition_assigns_straddler_to_is_leakage_safe():
    # One experiment spans the whole timeline (crosses the boundary) → IS, never
    # a clean OOS test.
    rows = [
        _row("early", "2010-01-01", "2011-12-31"),
        _row("straddle", "2010-01-01", "2019-12-31"),
        _row("late", "2019-01-01", "2019-12-31"),
    ]
    is_rows, oos_rows = partition_is_oos(rows, DEFAULT_POLICY)
    assert "straddle" in {r["experiment_id"] for r in is_rows}
    assert "straddle" not in {r["experiment_id"] for r in oos_rows}


def test_partition_missing_dates_go_to_is():
    rows = [_row("nod", None, None), _row("e", "2010-01-01", "2019-12-31")]
    is_rows, oos_rows = partition_is_oos(rows, DEFAULT_POLICY)
    assert "nod" in {r["experiment_id"] for r in is_rows}


def test_partition_boundary_is_per_market_universe():
    # Two (market,universe) cells with disjoint spans each split independently.
    rows = ([_row(f"A{i}", f"20{10+i:02d}-01-01", f"20{10+i:02d}-12-31",
                  market="IN") for i in range(10)]
            + [_row(f"B{i}", f"20{00+i:02d}-01-01", f"20{00+i:02d}-12-31",
                    market="US") for i in range(10)])
    is_rows, oos_rows = partition_is_oos(rows, DEFAULT_POLICY)
    oos_ids = {r["experiment_id"] for r in oos_rows}
    # Each cell contributes its own recent slice to OOS.
    assert any(x.startswith("A") for x in oos_ids)
    assert any(x.startswith("B") for x in oos_ids)


def test_partition_is_deterministic():
    rows = [_row(f"E{i}", f"20{10+i:02d}-01-01", f"20{10+i:02d}-12-31") for i in range(10)]
    a = partition_is_oos(list(reversed(rows)), DEFAULT_POLICY)
    b = partition_is_oos(rows, DEFAULT_POLICY)
    assert {r["experiment_id"] for r in a[1]} == {r["experiment_id"] for r in b[1]}


# --- §5.2 gate ------------------------------------------------------------

def _ev(hid="H", **kw):
    base = dict(is_mean=1.4, is_sd=0.08, is_n=17,
                oos_mean=1.3, oos_sd=0.12, oos_n=7)
    base.update(kw)
    return evaluate_holdout(hid, policy=DEFAULT_POLICY, **base)


def test_robust_strategy_passes_all_conditions():
    r = _ev()
    assert r.cond_sign and r.cond_exceed and r.cond_retention and r.cond_overlap
    assert r.holdout_pass is True
    assert r.method == "holdout_v1"


def test_overfit_fails_on_retention_and_overlap():
    r = _ev(is_mean=1.3, is_sd=0.10, oos_mean=0.05, oos_sd=0.20)
    assert r.cond_retention is False
    assert r.cond_overlap is False
    assert r.holdout_pass is False
    assert r.haircut is not None and r.haircut > 1.0   # large IS/OOS haircut


def test_sign_flip_fails():
    r = _ev(is_mean=1.0, is_sd=0.2, oos_mean=-0.5, oos_sd=0.2)
    assert r.cond_sign is False
    assert r.holdout_pass is False


def test_low_oos_exceedance_fails():
    # OOS effect positive in mean but too uncertain ⇒ Pr(θ_OOS>0) < 0.90.
    r = _ev(oos_mean=0.3, oos_sd=0.8)
    assert r.cond_exceed is False
    assert r.oos_exceed_prob < 0.90
    assert r.holdout_pass is False


def test_retention_below_min_fails():
    # retention 0.47 < 0.5 fails (c). (Sign and OOS-exceedance still hold; a large
    # relative drop like this also trips the overlap guard (d), which is expected —
    # (c) and (d) are correlated decay guards.)
    r = _ev(is_mean=0.85, is_sd=0.05, oos_mean=0.40, oos_sd=0.05)
    assert r.retention == pytest.approx(0.40 / 0.85, rel=1e-6)
    assert r.cond_retention is False
    assert r.cond_exceed and r.cond_sign
    assert r.holdout_pass is False


def test_overlap_fails_in_isolation():
    # retention 0.58 ≥ 0.5 and exceed passes, but the posteriors are too spread
    # for Pr(θ_IS−θ_OOS > Δ_max) ≤ 0.10.
    r = _ev(is_mean=1.2, is_sd=0.30, oos_mean=0.70, oos_sd=0.30)
    assert r.cond_retention is True
    assert r.cond_exceed is True
    assert r.cond_overlap is False
    assert r.holdout_pass is False


def test_delta_max_is_configurable():
    kw = dict(is_mean=1.2, is_sd=0.30, oos_mean=0.70, oos_sd=0.30)
    strict = evaluate_holdout("H", policy=HoldoutPolicy(delta_max=0.5), is_n=5, oos_n=5, **kw)
    loose = evaluate_holdout("H", policy=HoldoutPolicy(delta_max=2.0), is_n=5, oos_n=5, **kw)
    assert strict.cond_overlap is False
    assert loose.cond_overlap is True       # a wider tolerated gap passes (d)


def test_evaluate_is_a_pure_function():
    assert _ev() == _ev()


def test_haircut_recorded():
    r = _ev(is_mean=1.5, oos_mean=0.75)
    assert r.haircut == pytest.approx(1.5 / 0.75, rel=1e-6)
