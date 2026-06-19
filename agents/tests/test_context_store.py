"""Tests for context_store — regime classification, context observations,
cache rebuild, and context-keyed roll-ups (Milestone 9)."""

import pytest

from agents.storage import context_store as cs
from agents.storage.ledger_store import upsert_experiment


def _exp(eid: str, db_path) -> None:
    """A minimal experiment row so observation FKs resolve."""
    upsert_experiment({"experiment_id": eid, "status": "complete"}, db_path=db_path)


# --------------------------------------------------------------------------- #
# Regime classifier                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("vol,expected", [
    (0.05, "low_vol"),
    (0.149, "low_vol"),
    (0.15, "mid_vol"),
    (0.29, "mid_vol"),
    (0.30, "high_vol"),
    (0.80, "high_vol"),
    (None, cs.REGIME_ALL),
])
def test_classify_regime(vol, expected):
    assert cs.classify_regime(vol) == expected


def test_classify_regime_is_deterministic():
    assert cs.classify_regime(0.4) == cs.classify_regime(0.4)


def test_record_and_get_regime_label(tmp_db):
    _exp("EXP1", tmp_db)
    cs.record_regime_label("EXP1", "high_vol", db_path=tmp_db)
    assert cs.get_regime_label("EXP1", db_path=tmp_db) == "high_vol"


# --------------------------------------------------------------------------- #
# Observations + cache rebuild                                                #
# --------------------------------------------------------------------------- #

def _observe(tmp_db, eid, feat, market, universe, regime, sharpe, kept=1):
    _exp(eid, tmp_db)
    cs.add_context_observation(
        experiment_id=eid, feature_name=feat, market=market, universe=universe,
        regime=regime, bar_type=cs.DEFAULT_BAR_TYPE,
        attribution_method=cs.DEFAULT_ATTRIBUTION,
        net_sharpe=sharpe, net_calmar=sharpe, kept=kept, db_path=tmp_db)


def test_observation_is_idempotent(tmp_db):
    _observe(tmp_db, "E1", "mom20", "India", "NIFTY50", "high_vol", 1.5)
    _observe(tmp_db, "E1", "mom20", "India", "NIFTY50", "high_vol", 1.5)
    rows = cs.list_observations(feature_name="mom20", db_path=tmp_db)
    assert len(rows) == 1


def test_cache_rebuild_aggregates_per_cell(tmp_db):
    _observe(tmp_db, "E1", "mom20", "India", "NIFTY50", "high_vol", 1.0)
    _observe(tmp_db, "E2", "mom20", "India", "NIFTY50", "high_vol", 2.0)
    cs.rebuild_context_cache(tmp_db, min_n=2)
    cells = cs.context_performance(feature_name="mom20", db_path=tmp_db)
    assert len(cells) == 1
    c = cells[0]
    assert c["n_experiments"] == 2
    assert abs(c["avg_net_sharpe"] - 1.5) < 1e-9
    assert c["min_n_met"] == 1  # n>=2 meets default min_n


def test_context_cells_are_not_globally_merged(tmp_db):
    # Same signal, two markets -> two distinct cells, never one global number.
    _observe(tmp_db, "E1", "mom20", "India", "NIFTY50", "high_vol", 1.8)
    _observe(tmp_db, "E2", "mom20", "US", "SP500", "low_vol", -0.2)
    cs.rebuild_context_cache(tmp_db, min_n=1)
    cells = cs.context_performance(feature_name="mom20", db_path=tmp_db)
    assert len(cells) == 2
    markets = {c["market"] for c in cells}
    assert markets == {"India", "US"}


def test_context_performance_filters_by_market(tmp_db):
    _observe(tmp_db, "E1", "mom20", "India", "NIFTY50", "high_vol", 1.8)
    _observe(tmp_db, "E2", "mom20", "US", "SP500", "low_vol", -0.2)
    cs.rebuild_context_cache(tmp_db, min_n=1)
    india = cs.context_performance(market="India", db_path=tmp_db)
    assert len(india) == 1
    assert india[0]["market"] == "India"


def test_roll_up_matches_underlying_cells(tmp_db):
    _observe(tmp_db, "E1", "mom20", "India", "NIFTY50", "high_vol", 1.0)
    _observe(tmp_db, "E2", "mom20", "US", "SP500", "low_vol", 3.0)
    cs.rebuild_context_cache(tmp_db, min_n=1)
    glob = cs.roll_up(["feature_name"], db_path=tmp_db)
    assert len(glob) == 1
    # Honest re-aggregation of both observations.
    assert abs(glob[0]["avg_net_sharpe"] - 2.0) < 1e-9
    assert glob[0]["n_experiments"] == 2


def test_distinct_context_count(tmp_db):
    _observe(tmp_db, "E1", "mom20", "India", "NIFTY50", "high_vol", 1.0)
    _observe(tmp_db, "E2", "mom20", "US", "SP500", "low_vol", 1.0)
    cs.rebuild_context_cache(tmp_db, min_n=1)
    assert cs.distinct_context_count("mom20", min_n=1, db_path=tmp_db) == 2
    assert cs.distinct_context_count(
        "mom20", min_n=1, threshold=0.5, db_path=tmp_db) == 2
    assert cs.distinct_context_count(
        "mom20", min_n=1, threshold=5.0, db_path=tmp_db) == 0
