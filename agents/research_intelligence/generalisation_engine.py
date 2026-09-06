"""
GeneralisationProjector — project the §2.3 generalisation matrix (M11 PR-10, M11-6).

For a hypothesis, it folds the development evidence into cell posteriors (reusing
the shared stat_v1 primitives — the same fold the EvidenceProjector uses) and calls
the single-source ``generalisation_breakdown`` to persist, per (hypothesis ×
dimension), the survival counts (§2.3). It is the explainable per-dimension detail
behind the G-axis scalars already on ``hypothesis_state`` — it **re-derives no new
statistic and changes no promotion input** (the same τ_π and the same breakdown).

A **pure fold**: deterministic from the immutable log, idempotent, replay-stable.
It mutates no evidence and writes only its own projection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import evidence_store, generalisation_store
from .evidence_projector import DEVELOPMENT_SOURCES, rows_to_evidence
from .statistics import (
    DEFAULT_POLICY, StatPolicy, _measure, _cell_posterior,
    generalisation_breakdown,
)


class GeneralisationProjector:
    def __init__(self, db_path: Path = DB_PATH,
                 policy: StatPolicy = DEFAULT_POLICY) -> None:
        self.db_path = db_path
        self.policy = policy
        self.sources = frozenset(DEVELOPMENT_SOURCES)

    def rebuild_hypothesis(self, hypothesis_id: str) -> list[dict[str, Any]] | None:
        """Recompute and persist the generalisation matrix for one hypothesis.
        Returns the written dimension rows, or ``None`` if it has no usable
        development evidence."""
        rows = [
            e for e in evidence_store.list_evidence(
                hypothesis_id=hypothesis_id, db_path=self.db_path)
            if e["evidence_source"] in self.sources
        ]
        evidence = rows_to_evidence(rows, self.policy)
        if not evidence:
            generalisation_store.delete_matrix(hypothesis_id, db_path=self.db_path)
            return None

        measured = [_measure(e, self.policy) for e in evidence]
        by_cell: dict[tuple, list] = {}
        for md in measured:
            by_cell.setdefault(md.cell, []).append(md)
        cells = [_cell_posterior(cell, by_cell[cell], self.policy)
                 for cell in sorted(by_cell)]

        breakdown = generalisation_breakdown(cells, measured, self.policy)
        g_count = sum(1 for c in cells
                      if c.exceed_prob(self.policy) >= self.policy.tau_pi)
        g_coverage = sum(d.coverage for d in breakdown) / len(breakdown)

        matrix_rows = [
            {
                "dimension": d.dimension,
                "passing": d.passing,
                "available": d.available,
                "coverage": d.coverage,
                "g_count": g_count,
                "g_coverage": g_coverage,
                "method": self.policy.version,
            }
            for d in breakdown
        ]
        generalisation_store.replace_matrix(
            hypothesis_id, matrix_rows, db_path=self.db_path)
        return matrix_rows

    def rebuild_all(self) -> list[str]:
        """Rebuild the matrix for every hypothesis in the evidence log; prune
        hypotheses that no longer have development evidence."""
        current = set(evidence_store.distinct_hypothesis_ids(db_path=self.db_path))
        for hid in generalisation_store.distinct_hypotheses(db_path=self.db_path):
            if hid not in current:
                generalisation_store.delete_matrix(hid, db_path=self.db_path)

        rebuilt: list[str] = []
        for hid in sorted(current):
            if self.rebuild_hypothesis(hid) is not None:
                rebuilt.append(hid)
        return rebuilt
