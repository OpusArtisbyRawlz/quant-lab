"""
HoldoutEngine — project §5 holdout validation over the evidence log (M11 PR-4).

For each hypothesis, the engine reads its development-source ``evidence_event``
rows, splits them by the §5.1 calendar boundary into IS / OOS, computes **two
separate** ``stat_v1`` posteriors (reusing `statistics.assess_hypothesis` — no new
math), evaluates the four §5.2 gate conditions, and writes one row to the
rebuildable ``holdout_evaluation`` projection.

It is a **pure fold**: the evaluation is a deterministic function of the immutable
log, so a rebuild is idempotent and replay-stable. It is **fully separate from the
Promotion Engine** — it computes holdout evidence; promotion later *consumes* it
and never computes it. It writes only ``holdout_evaluation`` and mutates no
historical evidence.

Evidence sources: the same development set the PR-2 posterior pools
(``in_sample / validation / embargo / walk_forward``), re-split by calendar so the
OOS posterior is the most-recent slice of the development timeline (§5.1). Explicit
``holdout`` / ``live_paper`` source reconciliation is a separate, later concern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import evidence_store, holdout_store
from .evidence_projector import DEVELOPMENT_SOURCES, rows_to_evidence
from .statistics import DEFAULT_POLICY as STAT_DEFAULT_POLICY, StatPolicy, assess_hypothesis
from .holdout import (
    DEFAULT_POLICY as HOLDOUT_DEFAULT_POLICY, HoldoutPolicy,
    partition_is_oos, evaluate_holdout,
)


class HoldoutEngine:
    def __init__(self, db_path: Path = DB_PATH,
                 stat_policy: StatPolicy = STAT_DEFAULT_POLICY,
                 holdout_policy: HoldoutPolicy = HOLDOUT_DEFAULT_POLICY) -> None:
        self.db_path = db_path
        self.stat_policy = stat_policy
        self.holdout_policy = holdout_policy
        self.sources = frozenset(DEVELOPMENT_SOURCES)

    # -- rebuild one hypothesis -------------------------------------------
    def rebuild_hypothesis(self, hypothesis_id: str) -> dict[str, Any] | None:
        """Recompute and persist the holdout evaluation for one hypothesis.

        Returns the written ``holdout_evaluation`` row, or ``None`` when the
        hypothesis cannot be evaluated — it lacks usable evidence on *both* sides
        of the calendar boundary (no temporal holdout is possible).
        """
        rows = [
            e for e in evidence_store.list_evidence(
                hypothesis_id=hypothesis_id, db_path=self.db_path)
            if e["evidence_source"] in self.sources
        ]
        is_rows, oos_rows = partition_is_oos(rows, self.holdout_policy)

        is_ev = rows_to_evidence(is_rows, self.stat_policy)
        oos_ev = rows_to_evidence(oos_rows, self.stat_policy)
        if not is_ev or not oos_ev:
            return None  # no usable IS/OOS split → holdout not evaluable

        is_post = assess_hypothesis(is_ev, self.stat_policy)
        oos_post = assess_hypothesis(oos_ev, self.stat_policy)

        result = evaluate_holdout(
            hypothesis_id,
            is_mean=is_post.posterior_mean, is_sd=is_post.posterior_sd,
            is_n=len({e.experiment_id for e in is_ev}),
            oos_mean=oos_post.posterior_mean, oos_sd=oos_post.posterior_sd,
            oos_n=len({e.experiment_id for e in oos_ev}),
            policy=self.holdout_policy,
        )

        row = {
            "hypothesis_id": hypothesis_id,
            "is_mean": result.is_mean,
            "is_sd": result.is_sd,
            "is_n": result.is_n,
            "oos_mean": result.oos_mean,
            "oos_sd": result.oos_sd,
            "oos_n": result.oos_n,
            "oos_exceed_prob": result.oos_exceed_prob,
            "retention": result.retention,
            "overlap_prob": result.overlap_prob,
            "haircut": result.haircut,
            "cond_sign": 1 if result.cond_sign else 0,
            "cond_exceed": 1 if result.cond_exceed else 0,
            "cond_retention": 1 if result.cond_retention else 0,
            "cond_overlap": 1 if result.cond_overlap else 0,
            "holdout_pass": 1 if result.holdout_pass else 0,
            "holdout_fraction": self.holdout_policy.holdout_fraction,
            "retention_min": self.holdout_policy.retention_min,
            "delta_max": self.holdout_policy.delta_max,
            "method": result.method,
        }
        holdout_store.upsert_holdout(row, db_path=self.db_path)
        return row

    # -- rebuild everything -----------------------------------------------
    def rebuild_all(self) -> list[str]:
        """Rebuild holdout evaluations for every hypothesis in the evidence log.

        Returns the list of hypothesis_ids that produced an evaluation (those with
        a usable IS/OOS split).
        """
        rebuilt: list[str] = []
        for hid in evidence_store.distinct_hypothesis_ids(db_path=self.db_path):
            if self.rebuild_hypothesis(hid) is not None:
                rebuilt.append(hid)
        return rebuilt
