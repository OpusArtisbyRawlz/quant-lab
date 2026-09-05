"""
M11 PR-8 — Strategist decision consumption (integration + back-compat).

Proves the Strategist consumes the M11 posterior/stage/retirement via the clean
node_id → hypothesis_state join when ``use_evidence`` is on, and that the old M9
heuristic path is recovered exactly when evidence is absent or the flag is off.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables
from agents.storage import hypothesis_state_store, retirement_store
from agents.research_strategist.strategist import ResearchStrategist, StrategistConfig


def _db(tmp_path):
    db = tmp_path / "s.db"
    create_all_tables(db)
    return db


def _hs(db, node_id, pi, mu, g_count=1):
    hypothesis_state_store.upsert_hypothesis_state({
        "hypothesis_id": node_id, "q_stat_prob": pi, "posterior_mean": mu,
        "posterior_sd": 0.1, "ci_low": mu - 0.2, "ci_high": mu + 0.2,
        "g_count": g_count,
    }, db_path=db)


def _retire(db, node_id, state="Retired-Refuted"):
    retirement_store.upsert_retirement({
        "hypothesis_id": node_id, "retired": 1, "state": state, "refuted": 1,
    }, db_path=db)


def _node(nid, depth=1):
    return {"depth": depth, "experiment_id": "E1", "node_id": nid}


# --- evidence path (use_evidence=True) ------------------------------------

def test_confirmed_from_posterior(tmp_path):
    db = _db(tmp_path)
    _hs(db, "N", pi=0.99, mu=0.9)
    s = ResearchStrategist(db_path=db, config=StrategistConfig(use_evidence=True))
    assert s._confirmed("sig", "IN", "NIFTY", "time", node_id="N") is True


def test_refuted_from_low_pi(tmp_path):
    db = _db(tmp_path)
    _hs(db, "N", pi=0.01, mu=-0.5)
    s = ResearchStrategist(db_path=db, config=StrategistConfig(use_evidence=True))
    assert s._refuted("sig", "IN", "NIFTY", "time", node_id="N") is True
    assert s._confirmed("sig", "IN", "NIFTY", "time", node_id="N") is False


def test_retired_node_is_not_expandable_and_is_refuted(tmp_path):
    db = _db(tmp_path)
    _hs(db, "N", pi=0.99, mu=0.9)
    _retire(db, "N")
    s = ResearchStrategist(db_path=db, config=StrategistConfig(use_evidence=True))
    assert s._expandable(_node("N")) is False        # retired ⇒ terminal
    assert s._refuted("sig", "IN", "NIFTY", "time", node_id="N") is True
    assert s._confirmed("sig", "IN", "NIFTY", "time", node_id="N") is False


# --- back-compat: old heuristic recovered when evidence absent -------------

def test_no_posterior_falls_back_to_m9_heuristic(tmp_path):
    db = _db(tmp_path)
    # No M11 posterior for the node ⇒ the evidence path yields None ⇒ the M9
    # heuristic decides, so evidence-on and evidence-off agree exactly (old path
    # recovered when evidence is absent). With no M9 cell either, both say False.
    on = ResearchStrategist(db_path=db, config=StrategistConfig(use_evidence=True))
    off = ResearchStrategist(db_path=db, config=StrategistConfig(use_evidence=False))
    for pred in ("_confirmed", "_refuted"):
        a = getattr(on, pred)("sig", "IN", "NIFTY", "time", node_id="N")
        b = getattr(off, pred)("sig", "IN", "NIFTY", "time", node_id="N")
        assert a == b


def test_use_evidence_off_ignores_posterior(tmp_path):
    db = _db(tmp_path)
    _hs(db, "N", pi=0.99, mu=0.9)          # a strong posterior is present…
    off = ResearchStrategist(db_path=db, config=StrategistConfig(use_evidence=False))
    # …but with the flag off it is ignored entirely: the M9 path (no cell) decides.
    assert off._confirmed("sig", "IN", "NIFTY", "time", node_id="N") is False
    assert off._expandable(_node("N")) is True         # not gated by retirement


def test_default_config_is_evidence_off(tmp_path):
    assert StrategistConfig().use_evidence is False
