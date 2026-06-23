"""Tests for the Milestone 10 PR-2 HypothesisTreeManager and hypothesis_store."""

import pytest

from agents.storage import hypothesis_store
from agents.hypothesis_manager import (
    HypothesisTreeManager,
    HypothesisTreeError,
    VALID_OPERATORS,
    OP_REFINE,
    OP_VARY_BAR,
    OP_CROSS_MARKET,
    OP_ADD_FILTER,
    OP_COMBINE,
    OP_NEGATE,
)


# ---------------------------------------------------------------------------
# operators
# ---------------------------------------------------------------------------

def test_six_evolution_operators_defined():
    assert VALID_OPERATORS == {
        "refine", "vary_bar", "cross_market", "add_filter", "combine", "negate"
    }


def test_evolve_rejects_unknown_operator(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    root = mgr.create_root("camp_001", "momentum works")
    with pytest.raises(HypothesisTreeError):
        mgr.evolve(root["node_id"], "mutate", "something")


def test_evolve_rejects_combine_operator(tmp_db):
    """combine must go through combine(), not evolve()."""
    mgr = HypothesisTreeManager(db_path=tmp_db)
    root = mgr.create_root("camp_001", "h")
    with pytest.raises(HypothesisTreeError):
        mgr.evolve(root["node_id"], OP_COMBINE, "merged")


# ---------------------------------------------------------------------------
# node auditability + parent linkage
# ---------------------------------------------------------------------------

def test_root_node_is_auditable(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    root = mgr.create_root(
        "camp_001", "20-day momentum predicts returns",
        signals=["mom20"], market="India", universe="NIFTY50", bar_type="time",
        rationale="prior evidence")
    assert root["parent_id"] is None
    assert root["root_id"] == root["node_id"]
    assert root["depth"] == 0
    assert root["origin_operator"] is None
    assert root["signals"] == ["mom20"]
    assert root["market"] == "India"
    assert root["created_at"] is not None


def test_child_records_parent_and_operator(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    root = mgr.create_root("camp_001", "momentum", signals=["mom20"], market="India")
    child = mgr.evolve(root["node_id"], OP_REFINE, "momentum, 10-day",
                       signals=["mom10"])
    assert child["parent_id"] == root["node_id"]
    assert child["root_id"] == root["node_id"]
    assert child["depth"] == 1
    assert child["origin_operator"] == OP_REFINE
    # context inherited where not overridden
    assert child["market"] == "India"
    # an explicit edge was recorded carrying the operator
    edges = hypothesis_store.parents_of(child["node_id"], db_path=tmp_db)
    assert len(edges) == 1
    assert edges[0]["parent_id"] == root["node_id"]
    assert edges[0]["operator"] == OP_REFINE


def test_every_single_parent_operator_records_an_edge(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    root = mgr.create_root("camp_001", "h", market="India", bar_type="time")
    a = mgr.evolve(root["node_id"], OP_VARY_BAR, "h on dollar bars", bar_type="dollar")
    b = mgr.evolve(root["node_id"], OP_CROSS_MARKET, "h in US", market="US")
    c = mgr.evolve(root["node_id"], OP_ADD_FILTER, "h with liquidity filter")
    d = mgr.evolve(root["node_id"], OP_NEGATE, "h does NOT hold")
    ops = {e["child_id"]: e["operator"]
           for e in hypothesis_store.list_edges("camp_001", db_path=tmp_db)}
    assert ops[a["node_id"]] == OP_VARY_BAR
    assert ops[b["node_id"]] == OP_CROSS_MARKET
    assert ops[c["node_id"]] == OP_ADD_FILTER
    assert ops[d["node_id"]] == OP_NEGATE
    assert a["bar_type"] == "dollar"
    assert b["market"] == "US"


def test_evolve_unknown_parent_raises(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    with pytest.raises(HypothesisTreeError):
        mgr.evolve("ghost", OP_REFINE, "x")


# ---------------------------------------------------------------------------
# combine (multi-parent)
# ---------------------------------------------------------------------------

def test_combine_records_one_edge_per_parent(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    root = mgr.create_root("camp_001", "momentum", signals=["mom20"])
    p1 = mgr.evolve(root["node_id"], OP_REFINE, "fast momentum", signals=["mom10"])
    p2 = mgr.evolve(root["node_id"], OP_ADD_FILTER, "momentum + value",
                    signals=["mom20", "value"])
    merged = mgr.combine([p1["node_id"], p2["node_id"]],
                         "fast momentum + value", signals=["mom10", "value"])
    # primary parent recorded on the node
    assert merged["parent_id"] == p1["node_id"]
    assert merged["origin_operator"] == OP_COMBINE
    assert merged["depth"] == 2
    # one combine edge per parent
    edges = hypothesis_store.parents_of(merged["node_id"], db_path=tmp_db)
    assert len(edges) == 2
    assert {e["parent_id"] for e in edges} == {p1["node_id"], p2["node_id"]}
    assert all(e["operator"] == OP_COMBINE for e in edges)


def test_combine_requires_two_parents(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    root = mgr.create_root("camp_001", "h")
    with pytest.raises(HypothesisTreeError):
        mgr.combine([root["node_id"]], "x")


# ---------------------------------------------------------------------------
# reconstruction from storage
# ---------------------------------------------------------------------------

def _build_sample_tree(mgr, campaign_id="camp_001"):
    """Root with a child via every single-parent operator, plus a combine."""
    root = mgr.create_root(campaign_id, "momentum predicts returns",
                           node_id="n_root", signals=["mom20"],
                           market="India", universe="NIFTY50", bar_type="time")
    refine = mgr.evolve("n_root", OP_REFINE, "10-day momentum",
                        node_id="n_refine", signals=["mom10"])
    vary = mgr.evolve("n_root", OP_VARY_BAR, "momentum on dollar bars",
                      node_id="n_vary", bar_type="dollar")
    cross = mgr.evolve("n_root", OP_CROSS_MARKET, "momentum in US",
                       node_id="n_cross", market="US")
    filt = mgr.evolve("n_refine", OP_ADD_FILTER, "fast momentum + liquidity",
                      node_id="n_filter")
    neg = mgr.evolve("n_cross", OP_NEGATE, "momentum fails in US",
                     node_id="n_negate")
    combined = mgr.combine(["n_refine", "n_filter"], "fast momentum combo",
                           node_id="n_combine")
    return root


def test_reconstruct_tree_from_storage(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    _build_sample_tree(mgr)

    # Rebuild a fresh manager so nothing is cached in memory — everything must
    # come from storage.
    fresh = HypothesisTreeManager(db_path=tmp_db)
    tree = fresh.reconstruct_tree("n_root").to_dict()

    assert tree["node_id"] == "n_root"
    # primary-parent spanning tree: root's direct children
    direct = {c["node_id"] for c in tree["children"]}
    assert direct == {"n_refine", "n_vary", "n_cross"}

    # locate n_refine subtree
    refine = next(c for c in tree["children"] if c["node_id"] == "n_refine")
    refine_kids = {c["node_id"] for c in refine["children"]}
    # n_filter is refine's child; n_combine's PRIMARY parent is also n_refine
    assert refine_kids == {"n_filter", "n_combine"}

    cross = next(c for c in tree["children"] if c["node_id"] == "n_cross")
    assert {c["node_id"] for c in cross["children"]} == {"n_negate"}


def test_reconstructed_tree_preserves_all_operators(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    _build_sample_tree(mgr)
    edges = hypothesis_store.list_edges("camp_001", db_path=tmp_db)
    seen_ops = {e["operator"] for e in edges}
    # every single-parent operator + combine appears in the stored edges
    assert seen_ops == VALID_OPERATORS
    # combine produced two edges into the same child
    combine_edges = [e for e in edges if e["operator"] == OP_COMBINE]
    assert len(combine_edges) == 2
    assert {e["child_id"] for e in combine_edges} == {"n_combine"}


def test_reconstruct_matches_node_count(tmp_db):
    """Every stored node appears exactly once in the reconstructed spanning
    tree — proving lossless reconstruction."""
    mgr = HypothesisTreeManager(db_path=tmp_db)
    _build_sample_tree(mgr)
    stored = hypothesis_store.list_nodes("camp_001", db_path=tmp_db)
    stored_ids = {n["node_id"] for n in stored}

    fresh = HypothesisTreeManager(db_path=tmp_db)
    tree = fresh.reconstruct_tree("n_root")

    collected: list[str] = []

    def walk(t):
        collected.append(t.node["node_id"])
        for c in t.children:
            walk(c)

    walk(tree)
    assert sorted(collected) == sorted(stored_ids)
    assert len(collected) == len(set(collected))  # no duplication


def test_lineage_reconstructed_from_storage(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    _build_sample_tree(mgr)
    fresh = HypothesisTreeManager(db_path=tmp_db)
    path = [n["node_id"] for n in fresh.lineage("n_filter")]
    assert path == ["n_root", "n_refine", "n_filter"]


def test_reconstruct_forest_for_multiple_roots(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    mgr.create_root("camp_001", "tree A", node_id="a_root")
    mgr.evolve("a_root", OP_REFINE, "A.1", node_id="a_1")
    mgr.create_root("camp_001", "tree B", node_id="b_root")
    forest = HypothesisTreeManager(db_path=tmp_db).reconstruct_forest("camp_001")
    roots = {t.node["node_id"] for t in forest}
    assert roots == {"a_root", "b_root"}


# ---------------------------------------------------------------------------
# write-once links + sole-writer guard
# ---------------------------------------------------------------------------

def test_link_idea_and_experiment_are_write_once_stamps(tmp_db):
    mgr = HypothesisTreeManager(db_path=tmp_db)
    root = mgr.create_root("camp_001", "h", node_id="n_root")
    mgr.link_idea("n_root", "idea_001")
    mgr.link_experiment("n_root", "exp_001")
    node = mgr.get_node("n_root")
    assert node["idea_id"] == "idea_001"
    assert node["experiment_id"] == "exp_001"
    # hypothesis text itself is untouched (auditable, immutable)
    assert node["hypothesis"] == "h"


def test_hypothesis_manager_is_sole_writer_of_tree_tables(tmp_db):
    """No agents/ module other than hypothesis_store.py (the sanctioned DAL)
    issues write SQL against the hypothesis tables."""
    import re
    from pathlib import Path

    agents_dir = Path(__file__).resolve().parent.parent
    write_sql = re.compile(
        r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
        r"(hypothesis_node|hypothesis_edge)",
        re.IGNORECASE,
    )
    offenders = []
    for py in agents_dir.rglob("*.py"):
        if py.name == "hypothesis_store.py" or "tests" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        if write_sql.search(text):
            offenders.append(str(py.relative_to(agents_dir)))
    assert offenders == [], f"unexpected hypothesis-table writers: {offenders}"
