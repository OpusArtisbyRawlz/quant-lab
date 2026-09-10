"""
Phase 6 P6-5 — self-registering HypothesisSource registry + near-term sources.

Proves the generic, self-registration source architecture:
 - sources register themselves via ``@register`` (no orchestration edit);
 - the registry is built from those registrations for a context;
 - the loop stays agnostic to source origin (resolves by campaign_type only);
 - the three near-term sources (bar_type/overlay/replay) each propose deterministic,
   converging, append-only ``pending`` ideas that reuse the existing enqueue path.
"""

from __future__ import annotations

from agents.storage.db import create_all_tables, get_connection
from agents.campaign_manager import CampaignManager
from agents.research_loop import sources as S
from agents.research_loop.sources import SourceContext, Proposal


def _db(tmp_path, name="s.db"):
    db = tmp_path / name
    create_all_tables(db)
    return db


def _campaign(db, cid, campaign_type, scope):
    cm = CampaignManager(db_path=db)
    cm.create_campaign(cid, theme="t", goal_spec={"priority": 1},
                       scope=scope, campaign_type=campaign_type)
    cm.activate(cid)


def _ctx(db):
    return SourceContext(db_path=db, strategist=None)


def _pending(db, cid):
    with get_connection(db) as c:
        rows = c.execute(
            "SELECT idea_id, bar_type, hypothesis, campaign_id, status "
            "FROM pending_ideas WHERE campaign_id=? ORDER BY idea_id", (cid,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- registry / self-registration -----------------------------------------

def test_all_builtin_sources_self_register():
    types = S.registered_types()
    for t in (S.CAMPAIGN_TYPE_STRATEGY_EVOLUTION,
              S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON,
              S.CAMPAIGN_TYPE_OVERLAY_COMBINATION,
              S.CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY):
        assert t in types


def test_register_adds_without_touching_orchestration():
    @S.register("unit_test_type")
    def _make(ctx):
        class _Src:
            def propose(self, campaign_id):
                return []
        return _Src()
    try:
        reg = S.build_registry(SourceContext(strategist=None))
        assert "unit_test_type" in reg
        assert reg["unit_test_type"].propose("C") == []
    finally:
        S._REGISTRY.pop("unit_test_type", None)


def test_build_registry_is_deterministic():
    a = sorted(S.build_registry(SourceContext(strategist=None)))
    b = sorted(S.build_registry(SourceContext(strategist=None)))
    assert a == b


def test_sources_share_one_generic_interface():
    reg = S.build_registry(SourceContext(strategist=object()))
    for src in reg.values():
        assert hasattr(src, "propose")
        assert isinstance(src, S.HypothesisSource)


# --- bar_type_comparison ---------------------------------------------------

def test_bar_type_sweeps_scope_bar_types(tmp_path):
    db = _db(tmp_path)
    _campaign(db, "C", S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON, {
        "base": {"hypothesis": "edge X", "signals": ["s1"],
                 "market": "EQ", "universe": "SP500"},
        "bar_types": ["time", "volume", "dollar"],
    })
    src = S.build_registry(_ctx(db))[S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON]
    props = src.propose("C")
    assert len(props) == 3
    assert all(isinstance(p, Proposal) for p in props)
    rows = _pending(db, "C")
    assert sorted(r["bar_type"] for r in rows) == ["dollar", "time", "volume"]
    assert all(r["status"] == "pending" for r in rows)          # human gate intact


def test_bar_type_converges_no_duplicates(tmp_path):
    db = _db(tmp_path)
    _campaign(db, "C", S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON, {
        "base": {"hypothesis": "edge X", "signals": ["s1"]},
        "bar_types": ["time", "volume"],
    })
    src = S.build_registry(_ctx(db))[S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON]
    first = src.propose("C")
    second = src.propose("C")               # same state ⇒ nothing new
    assert len(first) == 2
    assert second == []
    assert len(_pending(db, "C")) == 2


def test_bar_type_no_base_is_noop(tmp_path):
    db = _db(tmp_path)
    _campaign(db, "C", S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON, {"bar_types": ["time"]})
    src = S.build_registry(_ctx(db))[S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON]
    assert src.propose("C") == []


# --- overlay_combination ---------------------------------------------------

def test_overlay_enumerates_combinations(tmp_path):
    db = _db(tmp_path)
    _campaign(db, "C", S.CAMPAIGN_TYPE_OVERLAY_COMBINATION, {
        "base": {"hypothesis": "edge Y", "signals": ["s1"]},
        "overlays": ["b", "a"],
        "max_overlay_combo": 2,
    })
    src = S.build_registry(_ctx(db))[S.CAMPAIGN_TYPE_OVERLAY_COMBINATION]
    props = src.propose("C")
    # singles a, b + pair a+b = 3, members sorted deterministically
    hyps = sorted(r["hypothesis"] for r in _pending(db, "C"))
    assert len(props) == 3
    assert hyps == [
        "edge Y | overlays=a",
        "edge Y | overlays=a+b",
        "edge Y | overlays=b",
    ]


def test_overlay_converges(tmp_path):
    db = _db(tmp_path)
    _campaign(db, "C", S.CAMPAIGN_TYPE_OVERLAY_COMBINATION, {
        "base": {"hypothesis": "edge Y"},
        "overlays": ["a"],
    })
    src = S.build_registry(_ctx(db))[S.CAMPAIGN_TYPE_OVERLAY_COMBINATION]
    assert len(src.propose("C")) == 1
    assert src.propose("C") == []


# --- counterfactual_replay -------------------------------------------------

def test_replay_reruns_specs_under_new_bar_types(tmp_path):
    db = _db(tmp_path)
    _campaign(db, "C", S.CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY, {
        "replay": [
            {"hypothesis": "prior edge", "signals": ["s1"],
             "market": "EQ", "universe": "SP500", "bar_types": ["volume", "dollar"]},
        ],
    })
    src = S.build_registry(_ctx(db))[S.CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY]
    props = src.propose("C")
    assert len(props) == 2
    rows = _pending(db, "C")
    assert sorted(r["bar_type"] for r in rows) == ["dollar", "volume"]
    # originals are never mutated — every replay is a NEW pending idea.
    assert all(r["hypothesis"] == "prior edge" for r in rows)
    assert all(r["status"] == "pending" for r in rows)


def test_replay_empty_scope_is_noop(tmp_path):
    db = _db(tmp_path)
    _campaign(db, "C", S.CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY, {})
    src = S.build_registry(_ctx(db))[S.CAMPAIGN_TYPE_COUNTERFACTUAL_REPLAY]
    assert src.propose("C") == []


# --- loop stays agnostic to source origin ----------------------------------

def test_loop_generate_routes_by_campaign_type(tmp_path):
    from agents.research_loop.loop import ResearchLoop, LoopConfig
    db = _db(tmp_path)
    _campaign(db, "C", S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON, {
        "base": {"hypothesis": "edge Z", "signals": ["s1"]},
        "bar_types": ["time", "volume"],
    })
    loop = ResearchLoop(db_path=db, config=LoopConfig(generate=True))
    out = loop._do_generate("T1", "C")
    assert out["campaign_type"] == S.CAMPAIGN_TYPE_BAR_TYPE_COMPARISON
    assert out["generated"] == 2
    assert len(out["idea_ids"]) == 2
