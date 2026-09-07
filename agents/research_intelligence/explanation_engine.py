"""
ExplanationWriter — project the M11-7 decision-record log (M11 PR-11).

A pure fold of the existing M11 projections into ``decision_record``: it explains
every promote / retire / reject decision by re-shaping the rows the promotion,
retirement, and failure engines already produced, plus the supporting /
contradictory experiment ids read straight from the evidence log. It **recomputes
no statistic** and mutates no evidence.

Deterministic and idempotent: the record set is a function of the immutable log +
the deterministic upstream projections; a rebuild reproduces identical rows and
prunes decisions whose subject has left the projections.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import (
    evidence_store, promotion_store, retirement_store, failure_store,
    decision_record_store,
)
from .evidence_projector import DEVELOPMENT_SOURCES
from .statistics import DEFAULT_POLICY
from . import explanation


class ExplanationWriter:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.sources = frozenset(DEVELOPMENT_SOURCES)
        self.s0 = DEFAULT_POLICY.S0

    def _support_split(self, hypothesis_id: str) -> tuple[list[str], list[str]]:
        """Supporting / contradictory experiment ids for a hypothesis, split by the
        sign of net Sharpe (development evidence). Provenance only — deterministic,
        no statistic recomputed."""
        support: set[str] = set()
        contra: set[str] = set()
        for e in evidence_store.list_evidence(hypothesis_id=hypothesis_id, db_path=self.db_path):
            if e["evidence_source"] not in self.sources:
                continue
            metrics = e.get("metrics") if isinstance(e.get("metrics"), dict) else {}
            ns = metrics.get("net_sharpe", metrics.get("sharpe")) if metrics else None
            if ns is None:
                continue
            if ns > self.s0:
                support.add(e["experiment_id"])
            elif ns < self.s0:
                contra.add(e["experiment_id"])
        return sorted(support), sorted(contra)

    def rebuild_all(self) -> dict[str, int]:
        """Rebuild every decision_record; prune stale subjects. Returns per-type
        counts written."""
        wanted: set[tuple[str, str]] = set()

        # promote — one per promotion recommendation
        n_promote = 0
        for reco in promotion_store.list_recommendations(db_path=self.db_path):
            sup, con = self._support_split(reco["hypothesis_id"])
            rec = explanation.build_promotion_record(reco, sup, con)
            decision_record_store.upsert_record(rec, db_path=self.db_path)
            wanted.add((rec["decision_type"], rec["subject_id"]))
            n_promote += 1

        # retire — one per retired hypothesis
        n_retire = 0
        for ret in retirement_store.list_retirements(retired=True, db_path=self.db_path):
            sup, con = self._support_split(ret["hypothesis_id"])
            rec = explanation.build_retirement_record(ret, sup, con)
            decision_record_store.upsert_record(rec, db_path=self.db_path)
            wanted.add((rec["decision_type"], rec["subject_id"]))
            n_retire += 1

        # reject — one per failed experiment
        n_reject = 0
        for fail in failure_store.list_failures(db_path=self.db_path):
            rec = explanation.build_rejection_record(fail)
            decision_record_store.upsert_record(rec, db_path=self.db_path)
            wanted.add((rec["decision_type"], rec["subject_id"]))
            n_reject += 1

        for existing in decision_record_store.list_records(db_path=self.db_path):
            key = (existing["decision_type"], existing["subject_id"])
            if key not in wanted:
                decision_record_store.delete_record(*key, db_path=self.db_path)

        return {"promote": n_promote, "retire": n_retire, "reject": n_reject}
