"""
campaign_attribution — read-only campaign attribution for the M10 workflow.

Every artefact the research loop produces can be attributed to its originating
campaign *without storing a campaign_id on each artefact*. Attribution is
**derived** at read time from the link keys that already exist:

    research_campaign
        ▲  (campaign_id)
        │
    hypothesis_node.campaign_id            pending_ideas.campaign_id
        │  (idea_id)                            │  (experiment_id)
        └───────────────► pending_ideas ◄───────┘
                                │  (experiment_id)
                                ▼
                          experiments
                          ╱          ╲
        lessons_learned.experiment_id   signal_context_observation.experiment_id

Because the only stored attribution anchors are ``pending_ideas.campaign_id`` and
``hypothesis_node.campaign_id`` (both additive columns, both write-once), this
module:

  * touches no execution, approval, or evaluation code — it only reads;
  * reconstructs attribution entirely from storage (requirement 1);
  * is unaffected by deleting/rebuilding a ``research_campaign`` projection row,
    since the anchors live on the ideas/hypotheses, not the campaign row
    (requirement 2);
  * leaves non-campaign experiments untouched — they simply have no anchor and
    resolve to no campaign (requirement 3);
  * lets campaign-tagged M9 observations be queried independently of the global
    observation table (requirement 4).

All functions are read-only and take an explicit ``db_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import get_connection, DB_PATH


def _loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


# ---------------------------------------------------------------------------
# Forward attribution: campaign -> its artefacts
# ---------------------------------------------------------------------------

def ideas_for_campaign(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    """All pending_ideas rows tagged to a campaign (any status)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pending_ideas WHERE campaign_id = ? "
            "ORDER BY created_at, idea_id",
            (campaign_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def hypotheses_for_campaign(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    """All hypothesis_node rows belonging to a campaign."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM hypothesis_node WHERE campaign_id = ? "
            "ORDER BY depth, created_at, node_id",
            (campaign_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if "signals" in d:
            d["signals"] = _loads(d["signals"])
        out.append(d)
    return out


def experiment_ids_for_campaign(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[str]:
    """Distinct experiment_ids produced by a campaign, derived through the
    campaign-tagged ideas that have been executed. Ordered for determinism."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT experiment_id FROM pending_ideas "
            "WHERE campaign_id = ? AND experiment_id IS NOT NULL "
            "AND experiment_id != '' ORDER BY experiment_id",
            (campaign_id,),
        ).fetchall()
    return [r["experiment_id"] for r in rows]


def experiments_for_campaign(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    """Full experiments rows attributed to a campaign (via executed tagged
    ideas). Empty for campaigns that have not produced any experiment yet."""
    ids = experiment_ids_for_campaign(campaign_id, db_path=db_path)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM experiments WHERE experiment_id IN ({placeholders}) "
            "ORDER BY experiment_id",
            ids,
        ).fetchall()
    return [dict(r) for r in rows]


def lessons_for_campaign(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    """Lessons learned on the campaign's experiments, derived through the
    experiment link (lessons carry no campaign_id of their own)."""
    ids = experiment_ids_for_campaign(campaign_id, db_path=db_path)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM lessons_learned WHERE experiment_id IN ({placeholders}) "
            "ORDER BY id",
            ids,
        ).fetchall()
    return [dict(r) for r in rows]


def observations_for_campaign(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    """M9 context observations attributed to a campaign, derived through the
    experiment link. This is the independent campaign-scoped view of the global
    signal_context_observation table (requirement 4): the observation rows
    themselves are never modified or duplicated."""
    ids = experiment_ids_for_campaign(campaign_id, db_path=db_path)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM signal_context_observation "
            f"WHERE experiment_id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
    return [dict(r) for r in rows]


def attribution_summary(
    campaign_id: str, *, db_path: Path = DB_PATH
) -> dict[str, int]:
    """Counts of each attributed artefact type for a campaign."""
    return {
        "hypotheses": len(hypotheses_for_campaign(campaign_id, db_path=db_path)),
        "ideas": len(ideas_for_campaign(campaign_id, db_path=db_path)),
        "experiments": len(experiment_ids_for_campaign(campaign_id, db_path=db_path)),
        "lessons": len(lessons_for_campaign(campaign_id, db_path=db_path)),
        "observations": len(observations_for_campaign(campaign_id, db_path=db_path)),
    }


# ---------------------------------------------------------------------------
# Reverse attribution: artefact -> its campaign
# ---------------------------------------------------------------------------

def campaign_for_experiment(
    experiment_id: str, *, db_path: Path = DB_PATH
) -> str | None:
    """The campaign an experiment belongs to, derived through the idea that
    produced it. Returns None for a non-campaign (ad-hoc) experiment — i.e. one
    with no campaign-tagged idea — leaving such experiments unchanged."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT campaign_id FROM pending_ideas "
            "WHERE experiment_id = ? AND campaign_id IS NOT NULL "
            "ORDER BY created_at LIMIT 1",
            (experiment_id,),
        ).fetchone()
    return row["campaign_id"] if row else None


def lineage_for_experiment(
    experiment_id: str, *, db_path: Path = DB_PATH
) -> dict[str, Any]:
    """Reconstruct the full attribution chain for an experiment, entirely from
    storage: campaign_id, the originating idea, any hypothesis node linked to
    that idea, and the experiment row. Fields are None where no link exists, so
    a non-campaign experiment yields {campaign_id: None, ...} without error."""
    with get_connection(db_path) as conn:
        idea = conn.execute(
            "SELECT * FROM pending_ideas WHERE experiment_id = ? "
            "ORDER BY created_at LIMIT 1",
            (experiment_id,),
        ).fetchone()
        idea = dict(idea) if idea else None

        node = None
        if idea is not None:
            node_row = conn.execute(
                "SELECT * FROM hypothesis_node WHERE idea_id = ? LIMIT 1",
                (idea["idea_id"],),
            ).fetchone()
            node = dict(node_row) if node_row else None

        exp = conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        exp = dict(exp) if exp else None

    return {
        "campaign_id": idea["campaign_id"] if idea else None,
        "idea": idea,
        "hypothesis_node": node,
        "experiment": exp,
    }
