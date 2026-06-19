"""Tests for the SignalLibrarian — context decomposition, regime labelling,
lifecycle transitions, generalization classes, backfill, idempotency (M9)."""

import json

from agents.signal_librarian.librarian import (
    SignalLibrarian, LibrarianConfig, PROMOTED, CANDIDATE, OBSERVED,
)
from agents.storage import signal_store as ss, context_store as cs
from agents.storage.ledger_store import upsert_experiment


def _exp(eid, *, features, market, universe, vol, net_sharpe, decision="keep",
         db_path=None):
    upsert_experiment({
        "experiment_id": eid,
        "status": "complete",
        "features": json.dumps(features),
        "market": market,
        "universe": universe,
        "vol": vol,
        "net_sharpe": net_sharpe,
        "net_calmar": net_sharpe,
        "decision": decision,
    }, db_path=db_path)


def test_record_experiment_decomposes_into_context(tmp_db):
    _exp("E1", features=["mom20"], market="India", universe="NIFTY50",
         vol=0.4, net_sharpe=1.8, db_path=tmp_db)
    lib = SignalLibrarian()
    res = lib.record_experiment("E1", db_path=tmp_db)
    assert res.processed
    assert res.regime == "high_vol"  # vol 0.4 -> high_vol
    assert res.features == ["mom20"]
    cells = cs.context_performance(feature_name="mom20", db_path=tmp_db)
    assert len(cells) == 1
    assert cells[0]["market"] == "India"
    assert cells[0]["regime"] == "high_vol"


def test_single_context_does_not_promote(tmp_db):
    # One market, one regime, single experiment -> below min_n, no promotion.
    _exp("E1", features=["mom20"], market="India", universe="NIFTY50",
         vol=0.4, net_sharpe=1.8, db_path=tmp_db)
    SignalLibrarian().record_experiment("E1", db_path=tmp_db)
    sig = ss.get_signal("mom20", db_path=tmp_db)
    assert sig["lifecycle_state"] in (OBSERVED, CANDIDATE)
    assert sig["lifecycle_state"] != PROMOTED


def test_multi_market_confirmation_promotes(tmp_db):
    # Same signal clears the bar in two distinct markets, min_n=1 -> promoted.
    lib = SignalLibrarian(LibrarianConfig(min_n=1))
    _exp("E1", features=["mom20"], market="India", universe="NIFTY50",
         vol=0.4, net_sharpe=1.8, db_path=tmp_db)
    _exp("E2", features=["mom20"], market="US", universe="SP500",
         vol=0.1, net_sharpe=1.2, db_path=tmp_db)
    lib.record_experiment("E1", db_path=tmp_db)
    lib.record_experiment("E2", db_path=tmp_db)
    sig = ss.get_signal("mom20", db_path=tmp_db)
    assert sig["lifecycle_state"] == PROMOTED
    assert sig["generalization_class"] == "universal"
    assert sig["promoted_at"] is not None


def test_promotion_logs_lifecycle_event_and_memory(tmp_db):
    from agents.storage import memory_store as ms
    lib = SignalLibrarian(LibrarianConfig(min_n=1))
    _exp("E1", features=["mom20"], market="India", universe="NIFTY50",
         vol=0.4, net_sharpe=1.8, db_path=tmp_db)
    _exp("E2", features=["mom20"], market="US", universe="SP500",
         vol=0.1, net_sharpe=1.2, db_path=tmp_db)
    lib.record_experiment("E1", db_path=tmp_db)
    lib.record_experiment("E2", db_path=tmp_db)
    events = ss.list_lifecycle_events(feature_name="mom20", db_path=tmp_db)
    assert any(e["to_state"] == PROMOTED for e in events)
    assert ms.memory_for_idea_generator(db_path=tmp_db)  # promotion memory written


def test_record_experiment_is_idempotent(tmp_db):
    lib = SignalLibrarian(LibrarianConfig(min_n=1))
    _exp("E1", features=["mom20"], market="India", universe="NIFTY50",
         vol=0.4, net_sharpe=1.8, db_path=tmp_db)
    lib.record_experiment("E1", db_path=tmp_db)
    lib.record_experiment("E1", db_path=tmp_db)
    obs = cs.list_observations(feature_name="mom20", db_path=tmp_db)
    assert len(obs) == 1  # no duplicate observations


def test_missing_experiment_is_not_processed(tmp_db):
    res = SignalLibrarian().record_experiment("NOPE", db_path=tmp_db)
    assert not res.processed
    assert res.reason == "experiment_not_found"


def test_no_features_is_not_processed(tmp_db):
    _exp("E1", features=[], market="India", universe="NIFTY50",
         vol=0.4, net_sharpe=1.8, db_path=tmp_db)
    res = SignalLibrarian().record_experiment("E1", db_path=tmp_db)
    assert not res.processed
    assert res.reason == "no_features"


def test_backfill_replays_all_experiments(tmp_db):
    lib = SignalLibrarian(LibrarianConfig(min_n=1))
    _exp("E1", features=["mom20"], market="India", universe="NIFTY50",
         vol=0.4, net_sharpe=1.8, db_path=tmp_db)
    _exp("E2", features=["rev5"], market="US", universe="SP500",
         vol=0.1, net_sharpe=0.9, db_path=tmp_db)
    results = lib.backfill(db_path=tmp_db)
    assert sum(r.processed for r in results) == 2
    assert ss.get_signal("mom20", db_path=tmp_db) is not None
    assert ss.get_signal("rev5", db_path=tmp_db) is not None
