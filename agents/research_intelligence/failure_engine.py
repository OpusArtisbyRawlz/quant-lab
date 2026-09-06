"""
FailureClassifier — project the §M11-5 failure taxonomy (M11 PR-9).

For each experiment in the immutable ``evidence_event`` log, the classifier
assembles the failure signals (critic decision, net Sharpe, sample size,
robustness flags), applies the pure ``failure_v1`` policy, and writes a
``failure_reason`` row for every failed/rejected experiment.

It is a **pure fold**: the classification is a deterministic function of the
immutable log, so a rebuild is idempotent and replay-stable. It **recomputes no
statistics**, mutates no evidence, and never touches the prose ``lessons_learned``
— ``failure_reason`` is its structured sibling. Reads only M11 storage
(``evidence_event``); it does not read or modify M7/M9/executor code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH
from agents.storage import evidence_store, failure_store
from .failure import (
    DEFAULT_POLICY, FailurePolicy, FailureSignals, classify,
)


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


class FailureClassifier:
    def __init__(self, db_path: Path = DB_PATH,
                 policy: FailurePolicy = DEFAULT_POLICY) -> None:
        self.db_path = db_path
        self.policy = policy

    def _signals(self, experiment_id: str) -> FailureSignals:
        """Aggregate one experiment's evidence rows into failure signals.
        Deterministic: rows are read oldest-first; the first usable value wins,
        flags are the sorted union."""
        rows = evidence_store.evidence_for_experiment(experiment_id, db_path=self.db_path)
        net_sharpe: float | None = None
        periods: float | None = None
        critic: str | None = None
        flags: set[str] = set()
        for r in rows:
            metrics = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
            if net_sharpe is None:
                net_sharpe = _num(metrics.get("net_sharpe")) if metrics else None
                if net_sharpe is None and metrics:
                    net_sharpe = _num(metrics.get("sharpe"))
            if periods is None and metrics:
                periods = _num(metrics.get("T")) or _num(metrics.get("n_periods"))
            if critic is None and r.get("critic_decision"):
                critic = r["critic_decision"]
            rf = r.get("robustness_flags")
            if isinstance(rf, list):
                flags.update(rf)
        return FailureSignals(
            experiment_id=experiment_id,
            critic_decision=critic,
            net_sharpe=net_sharpe,
            periods=int(periods) if periods is not None else None,
            robustness_flags=tuple(sorted(flags)),
        )

    def classify_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        """Classify one experiment; write/refresh or prune its ``failure_reason``.
        Returns the written row, or ``None`` if it is not a failure."""
        result = classify(self._signals(experiment_id), self.policy)
        if not result.is_failure:
            failure_store.delete_failure(experiment_id, db_path=self.db_path)
            return None
        failure_store.upsert_failure(
            experiment_id, result.reason_code, evidence=result.detail,
            method=self.policy.version, db_path=self.db_path)
        return failure_store.get_failure(experiment_id, db_path=self.db_path)

    def classify_all(self) -> list[str]:
        """Classify every experiment in the evidence log; prune stale rows.
        Returns the experiment_ids that were classified as failures."""
        current = set(evidence_store.distinct_experiment_ids(db_path=self.db_path))

        for existing in failure_store.list_failures(db_path=self.db_path):
            if existing["experiment_id"] not in current:
                failure_store.delete_failure(existing["experiment_id"], db_path=self.db_path)

        failures: list[str] = []
        for exp_id in sorted(current):
            if self.classify_experiment(exp_id) is not None:
                failures.append(exp_id)
        return failures
