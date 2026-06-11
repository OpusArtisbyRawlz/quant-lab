"""Tests for signal_store.py — signal_library table."""

import pytest
from agents.storage import signal_store as ss


SIG_BASE = {
    "feature_name": "momentum_20d",
    "signal_type": "momentum",
    "market": "US_equity",
    "universe": "sp500",
    "project_source": "project_04_return_forecast_alpha",
    "experiment_ids": ["EXP_004_FINAL"],
    "performance_contribution": 0.42,
    "weakness": "Underperforms in low-volatility regimes",
    "possible_combinations": ["vol_20d", "mean_reversion_5d"],
    "keep_reject_retest": "keep",
    "notes": "Strong IC in trending markets",
}


def test_upsert_and_get(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    sig = ss.get_signal("momentum_20d", db_path=tmp_db)
    assert sig is not None
    assert sig["signal_type"] == "momentum"
    assert isinstance(sig["experiment_ids"], list)
    assert isinstance(sig["possible_combinations"], list)


def test_upsert_is_idempotent(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    sigs = ss.list_signals(db_path=tmp_db)
    assert len(sigs) == 1


def test_upsert_updates_on_conflict(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    updated = SIG_BASE.copy()
    updated["performance_contribution"] = 0.99
    ss.upsert_signal(updated, db_path=tmp_db)
    sig = ss.get_signal("momentum_20d", db_path=tmp_db)
    assert abs(sig["performance_contribution"] - 0.99) < 1e-6


def test_add_experiment_to_signal(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    ss.add_experiment_to_signal("momentum_20d", "EXP_NEW_001", db_path=tmp_db)
    sig = ss.get_signal("momentum_20d", db_path=tmp_db)
    assert "EXP_NEW_001" in sig["experiment_ids"]


def test_add_experiment_no_duplicate(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    ss.add_experiment_to_signal("momentum_20d", "EXP_004_FINAL", db_path=tmp_db)
    sig = ss.get_signal("momentum_20d", db_path=tmp_db)
    assert sig["experiment_ids"].count("EXP_004_FINAL") == 1


def test_update_signal_status(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    ss.update_signal_status("momentum_20d", "retest", notes="Try with regime filter", db_path=tmp_db)
    sig = ss.get_signal("momentum_20d", db_path=tmp_db)
    assert sig["keep_reject_retest"] == "retest"
    assert "regime filter" in sig["notes"]


def test_list_signals_filter_type(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    rev = SIG_BASE.copy()
    rev["feature_name"] = "mean_reversion_5d"
    rev["signal_type"] = "mean_reversion"
    ss.upsert_signal(rev, db_path=tmp_db)

    mom = ss.list_signals(signal_type="momentum", db_path=tmp_db)
    assert len(mom) == 1
    assert mom[0]["feature_name"] == "momentum_20d"


def test_list_signals_filter_status(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    rej = SIG_BASE.copy()
    rej["feature_name"] = "bad_feature"
    rej["keep_reject_retest"] = "reject"
    ss.upsert_signal(rej, db_path=tmp_db)

    kept = ss.list_signals(status="keep", db_path=tmp_db)
    assert all(s["keep_reject_retest"] == "keep" for s in kept)


def test_get_combinable_signals(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    no_combo = SIG_BASE.copy()
    no_combo["feature_name"] = "orphan_signal"
    no_combo["possible_combinations"] = []
    ss.upsert_signal(no_combo, db_path=tmp_db)

    combinable = ss.get_combinable_signals(db_path=tmp_db)
    names = [s["feature_name"] for s in combinable]
    assert "momentum_20d" in names
    assert "orphan_signal" not in names


def test_get_weak_signals(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    weak = SIG_BASE.copy()
    weak["feature_name"] = "weak_rsi"
    weak["keep_reject_retest"] = "reject"
    ss.upsert_signal(weak, db_path=tmp_db)

    weaks = ss.get_weak_signals(db_path=tmp_db)
    assert any(s["feature_name"] == "weak_rsi" for s in weaks)
    assert all(s["keep_reject_retest"] in ("reject", "retest") for s in weaks)


def test_signal_summary(tmp_db):
    ss.upsert_signal(SIG_BASE.copy(), db_path=tmp_db)
    summary = ss.signal_summary(db_path=tmp_db)
    assert summary["total"] == 1
    assert "momentum" in summary["by_type"]


def test_get_nonexistent_signal(tmp_db):
    assert ss.get_signal("does_not_exist", db_path=tmp_db) is None
