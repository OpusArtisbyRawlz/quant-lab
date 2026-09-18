"""
Immutable origin provenance for recovered strategies.

Pure and deterministic: builds the origin-provenance record attached (write-once) to
every hypothesis/idea the historical-recovery pipeline enqueues, so each recovered
strategy stays permanently traceable to its exact origin. No new storage — the record
rides in the existing ``pending_ideas.metadata`` JSON; experiments/evidence reference
the idea by id (no duplication).

For Project 02 the origin points at the vendored historical notebook AND the
authoritative external GitHub repository (read from the vendored snapshot's
``provenance.json`` — the single source of those facts, not re-copied here). For the
in-repo projects (03-06) the origin is the quant-lab experiment record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# repo root = agents/recovery/ -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_P02_PROVENANCE = (_REPO_ROOT / "research" / "project_02_volatility_regime"
                   / "provenance.json")

# The canonical field set — every recovered hypothesis carries all of these keys.
PROVENANCE_FIELDS = (
    "origin_project",
    "origin_repository",
    "origin_commit",
    "origin_branch",
    "origin_notebook",
    "origin_artifact",
    "origin_strategy_name",
    "recovery_manifest_version",
    "recovery_timestamp",
    "vendored_snapshot",
)


def _p02_origin() -> dict[str, Any]:
    """Origin fields for Project 02, read from the vendored snapshot's provenance.json
    (authoritative repo/commit/notebook/artifact). Falls back gracefully if absent."""
    try:
        prov = json.loads(_P02_PROVENANCE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {
        "origin_repository": prov.get("authoritative_repo_url"),
        "origin_commit": prov.get("authoritative_repo_commit"),
        "origin_branch": prov.get("source_branch"),
        "origin_notebook": prov.get("authoritative_notebook_path"),
        "origin_artifact": (prov.get("imported_artifact") or {}).get("path")
                           or (prov.get("original_output_artifacts") or [None])[0],
        "vendored_snapshot": True,
        "vendored_path": "research/project_02_volatility_regime/",
    }


def build_provenance(
    strategy: dict[str, Any],
    *,
    manifest_version: str,
    recovery_timestamp: str,
) -> dict[str, Any]:
    """Build the immutable origin-provenance record for one recovered strategy.

    Deterministic pure function of the manifest entry (+ the vendored P02
    provenance.json for Project 02). ``recovery_timestamp`` is supplied by the caller
    (the recovery source uses the campaign's own ``created_at`` — an existing,
    immutable value — so replay never regenerates it)."""
    project = strategy["project"]
    record: dict[str, Any] = {
        "origin_project": project,
        "origin_repository": None,
        "origin_commit": None,
        "origin_branch": None,
        "origin_notebook": None,
        "origin_artifact": None,
        "origin_strategy_name": strategy["strategy_id"],
        "recovery_manifest_version": manifest_version,
        "recovery_timestamp": recovery_timestamp,
        "vendored_snapshot": False,
    }
    if project == "project_02_volatility_regime":
        # Recovered from the authoritative external repo, vendored locally.
        record.update(_p02_origin())
    else:
        # In-repo historical projects (03-06): origin is the quant-lab experiment.
        record["origin_repository"] = "OpusArtisbyRawlz/quant-lab (in-repo experiments)"
        exp = strategy.get("experiment_id")
        record["origin_artifact"] = (
            f"experiments/completed/{exp}" if exp else None)
    return record


def read_idea_provenance(idea_id: str, *, db_path: Any = None) -> dict[str, Any] | None:
    """Read the immutable origin provenance recorded on a recovered hypothesis/idea,
    or None if the idea has none. Reference-by-id: experiments/evidence link back to
    this idea, so this is the single lookup for the whole downstream chain."""
    from agents.idea_generator import approval_queue
    from agents.storage.db import DB_PATH
    idea = approval_queue.get_idea(idea_id, db_path=db_path or DB_PATH)
    if not idea:
        return None
    meta = idea.get("metadata") or {}
    if isinstance(meta, dict):
        return meta.get("provenance")
    return None


def is_complete(provenance: dict[str, Any]) -> bool:
    """True if a provenance record carries every canonical field with a non-empty
    ``origin_project`` / ``origin_strategy_name`` / ``recovery_manifest_version``."""
    if any(f not in provenance for f in PROVENANCE_FIELDS):
        return False
    return bool(provenance.get("origin_project")
                and provenance.get("origin_strategy_name")
                and provenance.get("recovery_manifest_version"))
