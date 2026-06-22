"""
campaign_report_store — read-only reporting over the Milestone 10 autonomous
research loop (campaigns, scheduler, hypothesis trees, signal lifecycle).

Like context_report_store, this module never writes and issues no SQL of its
own. It composes the read APIs of the storage layer
(campaign_store, campaign_attribution, scheduler_store, hypothesis_store,
context_store, signal_store, lessons_store) into typed, frozen reporting
dataclasses. Everything it returns is reconstructible purely from stored state:

  * Campaign overview / ranking / stalled board   -> campaign_store + attribution
  * Exploration vs exploitation accounting          -> scheduler_event log
  * Productive contexts                             -> context_store cache
  * Recently learned knowledge                      -> lessons_learned
  * Signal lifecycle board                          -> signal_library lifecycle
  * Hypothesis evolution tree                       -> hypothesis_node/edge

Campaign state is always derived through
``campaign_store.reconstruct_state_from_events`` so the report agrees with the
authoritative event log rather than the projection row. The exploration
accounting mirrors ``ResearchScheduler.exploration_stats`` exactly, reading the
same append-only ``scheduler_event`` evidence, so a report and a live scheduler
can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import campaign_store as cms
from agents.storage import campaign_attribution as attr
from agents.storage import scheduler_store as sched
from agents.storage import hypothesis_store as hs
from agents.storage import context_store as cs
from agents.storage import signal_store as ss
from agents.storage import lessons_store as ls


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CampaignOverviewStat:
    """One campaign's headline state + attributed artefact counts."""
    campaign_id: str
    theme: str
    state: str | None
    budget_experiments: int
    budget_spent: int
    exploration_fraction: float
    n_hypotheses: int
    n_ideas: int
    n_experiments: int
    n_lessons: int
    n_observations: int
    n_with_net: int
    avg_net_sharpe: float | None
    best_net_sharpe: float | None


@dataclass(frozen=True)
class CampaignRankStat:
    """A campaign's standing in the deterministic productivity ranking."""
    rank: int
    campaign_id: str
    theme: str
    state: str | None
    n_experiments: int
    avg_net_sharpe: float | None
    best_net_sharpe: float | None


@dataclass(frozen=True)
class StalledCampaignStat:
    campaign_id: str
    theme: str
    budget_experiments: int
    budget_spent: int
    n_experiments: int
    stall_patience: int


@dataclass(frozen=True)
class ExplorationStat:
    """Explore/exploit dispatch accounting, reconstructed from the log."""
    campaign_id: str | None
    explore: int
    exploit: int
    unknown: int
    total: int
    explore_fraction: float


@dataclass(frozen=True)
class ProductiveContextStat:
    feature_name: str
    market: str
    universe: str
    regime: str
    bar_type: str
    n_experiments: int
    avg_net_sharpe: float | None
    contribution_score: float | None


@dataclass(frozen=True)
class RecentLessonStat:
    experiment_id: str | None
    category: str | None
    confidence: str | None
    finding: str | None
    implication: str | None
    created_at: str | None


@dataclass(frozen=True)
class LifecycleBucketStat:
    lifecycle_state: str
    n_signals: int
    feature_names: tuple[str, ...]


@dataclass(frozen=True)
class HypothesisTreeNode:
    node_id: str
    parent_id: str | None
    depth: int
    hypothesis: str
    origin_operator: str | None
    operator_in: str | None          # operator on the edge that produced this node
    idea_id: str | None
    experiment_id: str | None
    children: tuple["HypothesisTreeNode", ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _net_metrics(experiments: list[dict]) -> tuple[int, float | None, float | None]:
    """(#experiments with a net_sharpe, avg net_sharpe, best net_sharpe)."""
    nets = [e["net_sharpe"] for e in experiments
            if e.get("net_sharpe") is not None]
    if not nets:
        return 0, None, None
    avg = round(sum(nets) / len(nets), 6)
    return len(nets), avg, round(max(nets), 6)


# ---------------------------------------------------------------------------
# 1. Campaign overview
# ---------------------------------------------------------------------------

def campaign_overview(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> CampaignOverviewStat | None:
    """Headline state + attributed artefact counts for one campaign.

    State is derived from the event log (authoritative), never the projection
    row. Returns None if the campaign has no projection row."""
    camp = cms.get_campaign(campaign_id, db_path=db_path)
    if camp is None:
        return None
    state = cms.reconstruct_state_from_events(campaign_id, db_path=db_path)
    summary = attr.attribution_summary(campaign_id, db_path=db_path)
    experiments = attr.experiments_for_campaign(campaign_id, db_path=db_path)
    n_with_net, avg_net, best_net = _net_metrics(experiments)
    return CampaignOverviewStat(
        campaign_id=campaign_id,
        theme=camp.get("theme", ""),
        state=state,
        budget_experiments=int(camp.get("budget_experiments", 0)),
        budget_spent=int(camp.get("budget_spent", 0)),
        exploration_fraction=float(camp.get("exploration_fraction", 0.0)),
        n_hypotheses=summary["hypotheses"],
        n_ideas=summary["ideas"],
        n_experiments=summary["experiments"],
        n_lessons=summary["lessons"],
        n_observations=summary["observations"],
        n_with_net=n_with_net,
        avg_net_sharpe=avg_net,
        best_net_sharpe=best_net,
    )


def all_campaign_overviews(
    *, db_path: Path = DB_PATH
) -> list[CampaignOverviewStat]:
    """Overview for every campaign, ordered by created_at (list_campaigns)."""
    out: list[CampaignOverviewStat] = []
    for camp in cms.list_campaigns(db_path=db_path):
        ov = campaign_overview(camp["campaign_id"], db_path=db_path)
        if ov is not None:
            out.append(ov)
    return out


# ---------------------------------------------------------------------------
# 2. Campaign ranking
# ---------------------------------------------------------------------------

def campaign_ranking(*, db_path: Path = DB_PATH) -> list[CampaignRankStat]:
    """Deterministic productivity ranking across all campaigns.

    Sort key: most experiments first, then highest avg net_sharpe (None last),
    then campaign_id as a stable final tiebreak. Purely a function of stored
    state, so two calls always return the same order."""
    overviews = all_campaign_overviews(db_path=db_path)
    ordered = sorted(
        overviews,
        key=lambda o: (
            -o.n_experiments,
            o.avg_net_sharpe is None,
            -(o.avg_net_sharpe or 0.0),
            o.campaign_id,
        ),
    )
    return [
        CampaignRankStat(
            rank=i + 1,
            campaign_id=o.campaign_id,
            theme=o.theme,
            state=o.state,
            n_experiments=o.n_experiments,
            avg_net_sharpe=o.avg_net_sharpe,
            best_net_sharpe=o.best_net_sharpe,
        )
        for i, o in enumerate(ordered)
    ]


# ---------------------------------------------------------------------------
# 3. Stalled campaigns
# ---------------------------------------------------------------------------

def stalled_campaigns(*, db_path: Path = DB_PATH) -> list[StalledCampaignStat]:
    """Campaigns whose authoritative (event-log) state is STALLED."""
    out: list[StalledCampaignStat] = []
    for camp in cms.list_campaigns(db_path=db_path):
        cid = camp["campaign_id"]
        if cms.reconstruct_state_from_events(cid, db_path=db_path) != cms.STATE_STALLED:
            continue
        n_exp = len(attr.experiment_ids_for_campaign(cid, db_path=db_path))
        out.append(StalledCampaignStat(
            campaign_id=cid,
            theme=camp.get("theme", ""),
            budget_experiments=int(camp.get("budget_experiments", 0)),
            budget_spent=int(camp.get("budget_spent", 0)),
            n_experiments=n_exp,
            stall_patience=int(camp.get("stall_patience", 0)),
        ))
    out.sort(key=lambda s: s.campaign_id)
    return out


# ---------------------------------------------------------------------------
# 4. Exploration vs exploitation
# ---------------------------------------------------------------------------

def exploration_report(
    *, campaign_id: str | None = None, db_path: Path = DB_PATH
) -> ExplorationStat:
    """Explore/exploit dispatch accounting reconstructed from the scheduler log.

    This mirrors ResearchScheduler.exploration_stats exactly — it reads the same
    append-only ``scheduler_event`` dispatched events and counts the ``bucket``
    recorded in each event's evidence — so a report can never disagree with the
    scheduler's own accounting."""
    explore = exploit = unknown = 0
    for e in sched.list_events(action=sched.ACTION_DISPATCHED, db_path=db_path):
        if campaign_id is not None and e.get("campaign_id") != campaign_id:
            continue
        ev = e.get("evidence")
        bucket = ev.get("bucket") if isinstance(ev, dict) else None
        if bucket == "explore":
            explore += 1
        elif bucket == "exploit":
            exploit += 1
        else:
            unknown += 1
    total = explore + exploit + unknown
    return ExplorationStat(
        campaign_id=campaign_id,
        explore=explore,
        exploit=exploit,
        unknown=unknown,
        total=total,
        explore_fraction=round(explore / total, 6) if total else 0.0,
    )


# ---------------------------------------------------------------------------
# 5. Productive contexts
# ---------------------------------------------------------------------------

def productive_contexts(
    *, top: int = 10, min_n: int | None = None, db_path: Path = DB_PATH
) -> list[ProductiveContextStat]:
    """The most productive context cells overall, strongest contribution first.

    context_store.context_performance already orders by contribution_score
    descending (NULLs last), then n_experiments — a deterministic order."""
    rows = cs.context_performance(min_n=min_n, db_path=db_path)
    out = [
        ProductiveContextStat(
            feature_name=r["feature_name"],
            market=r["market"],
            universe=r["universe"],
            regime=r["regime"],
            bar_type=r["bar_type"],
            n_experiments=r["n_experiments"],
            avg_net_sharpe=r["avg_net_sharpe"],
            contribution_score=r["contribution_score"],
        )
        for r in rows
    ]
    return out[:top]


# ---------------------------------------------------------------------------
# 6. Recently learned knowledge
# ---------------------------------------------------------------------------

def recent_knowledge(
    *, limit: int = 20, db_path: Path = DB_PATH
) -> list[RecentLessonStat]:
    """Most recently recorded lessons (lessons_store orders by created_at desc)."""
    rows = ls.list_lessons(limit=limit, db_path=db_path)
    return [
        RecentLessonStat(
            experiment_id=r.get("experiment_id"),
            category=r.get("category"),
            confidence=r.get("confidence"),
            finding=r.get("finding"),
            implication=r.get("implication"),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 7. Signal lifecycle board
# ---------------------------------------------------------------------------

def signal_lifecycle_board(
    *, db_path: Path = DB_PATH
) -> list[LifecycleBucketStat]:
    """Signals grouped by lifecycle_state, ordered by a fixed lifecycle order."""
    buckets: dict[str, list[str]] = {}
    for sig in ss.list_by_lifecycle(db_path=db_path):
        state = sig.get("lifecycle_state") or "observed"
        buckets.setdefault(state, []).append(sig["feature_name"])
    order = {"promoted": 0, "candidate": 1, "observed": 2, "retired": 3}
    out = [
        LifecycleBucketStat(
            lifecycle_state=state,
            n_signals=len(names),
            feature_names=tuple(sorted(names)),
        )
        for state, names in buckets.items()
    ]
    out.sort(key=lambda b: (order.get(b.lifecycle_state, 9), b.lifecycle_state))
    return out


# ---------------------------------------------------------------------------
# 8. Hypothesis evolution tree
# ---------------------------------------------------------------------------

def hypothesis_tree(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[HypothesisTreeNode]:
    """Reconstruct a campaign's hypothesis forest from stored nodes + edges.

    Roots (parent_id IS NULL) become the top of each tree; children are attached
    via parent_id and ordered deterministically by (depth, node_id). The
    operator that produced each child is read from the matching hypothesis_edge.
    Pure read: no SQL of its own beyond the storage read APIs."""
    nodes = hs.list_nodes(campaign_id, db_path=db_path)
    edges = hs.list_edges(campaign_id, db_path=db_path)

    # operator on the edge that produced a given child
    op_in: dict[str, str] = {}
    for e in edges:
        op_in.setdefault(e["child_id"], e.get("operator"))

    children_by_parent: dict[str | None, list[dict]] = {}
    for n in nodes:
        children_by_parent.setdefault(n.get("parent_id"), []).append(n)
    for kids in children_by_parent.values():
        kids.sort(key=lambda n: (n.get("depth", 0), n["node_id"]))

    def build(node: dict) -> HypothesisTreeNode:
        kids = children_by_parent.get(node["node_id"], [])
        return HypothesisTreeNode(
            node_id=node["node_id"],
            parent_id=node.get("parent_id"),
            depth=int(node.get("depth", 0)),
            hypothesis=node.get("hypothesis", ""),
            origin_operator=node.get("origin_operator"),
            operator_in=op_in.get(node["node_id"]),
            idea_id=node.get("idea_id"),
            experiment_id=node.get("experiment_id"),
            children=tuple(build(k) for k in kids),
        )

    roots = children_by_parent.get(None, [])
    roots.sort(key=lambda n: (n.get("depth", 0), n["node_id"]))
    return [build(r) for r in roots]
