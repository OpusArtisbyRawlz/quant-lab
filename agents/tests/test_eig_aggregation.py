"""
Phase 6 P6-14 — campaign-level EIG aggregation (derive + cache).

Proves CampaignManager derives a campaign's Expected Information Gain by aggregating
the already-computed M11 `budget_allocation.evoi` over the campaign's live
(non-retired) hypotheses (design §5) — not a new statistic, no M11 change — and
caches it on `research_campaign.expected_information_gain` (CM is the sole writer).
`eig_spec.aggregate` ∈ {mean (default), sum, max}; promotion_headroom is deferred
(falls back to mean). Pure compute; deterministic; rebuild-stable; feeds P6-13.
"""

from __future__ import annotations

import pytest

from agents.storage.db import create_all_tables
from agents.storage import evidence_store, budget_store, campaign_store
from agents.campaign_manager import CampaignManager, CampaignError
from agents.portfolio_planner import PortfolioPlanner


def _db(tmp_path, name="eig.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _cm(db):
    return CampaignManager(db_path=db)


def _hyp(db, campaign_id, hid, evoi, *, retired=0):
    """Attribute a hypothesis to a campaign (evidence_event) with an EVOI/retired
    budget_allocation row — the exact stores M11 writes."""
    evidence_store.record_evidence(
        f"E_{campaign_id}_{hid}", hypothesis_id=hid, campaign_id=campaign_id, db_path=db)
    budget_store.upsert_budget(
        {"hypothesis_id": hid, "evoi": float(evoi), "retired": int(retired)}, db_path=db)


def _campaign(cm, cid, **fields):
    cm.create_campaign(cid, theme="t", **fields)
    cm.activate(cid)


# --- aggregation modes -----------------------------------------------------

def test_mean_is_default(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C")                          # no eig_spec ⇒ mean
    _hyp(db, "C", "h1", 2.0)
    _hyp(db, "C", "h2", 4.0)
    assert cm.compute_eig("C") == 3.0


def test_sum_aggregate(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C", eig_spec={"aggregate": "sum"})
    _hyp(db, "C", "h1", 2.0)
    _hyp(db, "C", "h2", 4.0)
    assert cm.compute_eig("C") == 6.0


def test_max_aggregate(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C", eig_spec={"aggregate": "max"})
    _hyp(db, "C", "h1", 2.0)
    _hyp(db, "C", "h2", 7.0)
    assert cm.compute_eig("C") == 7.0


def test_unknown_aggregate_falls_back_to_mean(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C", eig_spec={"aggregate": "promotion_headroom"})   # deferred
    _hyp(db, "C", "h1", 2.0)
    _hyp(db, "C", "h2", 4.0)
    assert cm.compute_eig("C") == 3.0          # mean fallback


# --- live-set semantics (§5) -----------------------------------------------

def test_retired_hypotheses_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C", eig_spec={"aggregate": "sum"})
    _hyp(db, "C", "live1", 2.0)
    _hyp(db, "C", "live2", 4.0)
    _hyp(db, "C", "dead", 99.0, retired=1)      # excluded from the set
    assert cm.compute_eig("C") == 6.0


def test_hypothesis_without_budget_row_excluded(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C", eig_spec={"aggregate": "sum"})
    _hyp(db, "C", "allocated", 5.0)
    # attribute a hypothesis via evidence but write NO budget_allocation row.
    evidence_store.record_evidence("E_nobudget", hypothesis_id="unallocated",
                                   campaign_id="C", db_path=db)
    assert cm.compute_eig("C") == 5.0


def test_empty_campaign_is_zero(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C")
    assert cm.compute_eig("C") == 0.0


def test_all_retired_decays_to_zero(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C")
    _hyp(db, "C", "h1", 5.0, retired=1)
    _hyp(db, "C", "h2", 8.0, retired=1)
    assert cm.compute_eig("C") == 0.0          # played-out campaign


def test_hypotheses_scoped_per_campaign(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "A", eig_spec={"aggregate": "sum"})
    _campaign(cm, "B", eig_spec={"aggregate": "sum"})
    _hyp(db, "A", "a1", 3.0)
    _hyp(db, "B", "b1", 10.0)
    assert cm.compute_eig("A") == 3.0          # B's hypothesis does not leak in
    assert cm.compute_eig("B") == 10.0


def test_compute_unknown_campaign_raises(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(CampaignError):
        _cm(db).compute_eig("nope")


# --- caching ---------------------------------------------------------------

def test_refresh_eig_caches_on_campaign(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C", eig_spec={"aggregate": "sum"})
    _hyp(db, "C", "h1", 2.0)
    _hyp(db, "C", "h2", 4.0)
    assert campaign_store.get_campaign("C", db_path=db)["expected_information_gain"] is None
    v = cm.refresh_eig("C")
    assert v == 6.0
    assert campaign_store.get_campaign("C", db_path=db)["expected_information_gain"] == 6.0


def test_refresh_all_eig(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "A")
    _campaign(cm, "B")
    _hyp(db, "A", "a1", 4.0)
    _hyp(db, "B", "b1", 8.0)
    out = cm.refresh_all_eig()
    assert out == {"A": 4.0, "B": 8.0}
    assert list(out.keys()) == ["A", "B"]      # sorted / deterministic


def test_refresh_updates_stale_cache(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C", eig_spec={"aggregate": "sum"})
    _hyp(db, "C", "h1", 2.0)
    assert cm.refresh_eig("C") == 2.0
    _hyp(db, "C", "h2", 5.0)                    # new evidence
    assert cm.refresh_eig("C") == 7.0          # re-derived, cache updated


# --- purity / determinism / rebuild ----------------------------------------

def test_compute_is_pure_no_mutation(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C")
    _hyp(db, "C", "h1", 3.0)
    before = campaign_store.get_campaign("C", db_path=db)["expected_information_gain"]
    cm.compute_eig("C")
    cm.compute_eig("C")
    after = campaign_store.get_campaign("C", db_path=db)["expected_information_gain"]
    assert before == after is None             # compute never writes the cache


def test_deterministic_replay(tmp_path):
    def build(name):
        db = _db(tmp_path, name)
        cm = _cm(db)
        _campaign(cm, "C", eig_spec={"aggregate": "mean"})
        _hyp(db, "C", "h2", 4.0)
        _hyp(db, "C", "h1", 2.0)
        _hyp(db, "C", "h3", 9.0, retired=1)
        return cm.compute_eig("C")
    assert build("r1.db") == build("r2.db") == 3.0


def test_compute_stable_across_rebuild(tmp_path):
    db = _db(tmp_path)
    cm = _cm(db)
    _campaign(cm, "C", eig_spec={"aggregate": "sum"})
    _hyp(db, "C", "h1", 2.0)
    _hyp(db, "C", "h2", 4.0)
    before = cm.compute_eig("C")
    cm.rebuild_from_events("C")                 # projection rebuilt from the log
    assert cm.compute_eig("C") == before == 6.0  # derived from budget_allocation, not the row


# --- integration with P6-13 budget -----------------------------------------

def test_refreshed_eig_feeds_eig_proportional_budget(tmp_path):
    """End-to-end: refresh_eig populates the cached column that P6-13's
    eig_proportional budget mode consumes."""
    db = _db(tmp_path)
    cm = _cm(db)
    cm.create_portfolio("P1", "Alpha",
                        budget_spec={"total": 20, "mode": "eig_proportional",
                                     "a_max": 1.0})
    cm.create_campaign("lo", theme="t", portfolio_id="P1"); cm.activate("lo")
    cm.create_campaign("hi", theme="t", portfolio_id="P1"); cm.activate("hi")
    _hyp(db, "lo", "l1", 1.0)
    _hyp(db, "hi", "h1", 3.0)
    cm.refresh_all_eig()                        # populate the cached EIG column
    alloc = PortfolioPlanner(db_path=db).allocate_budget("P1")
    assert alloc.allocations == {"hi": 15, "lo": 5}   # 3:1 by EIG
