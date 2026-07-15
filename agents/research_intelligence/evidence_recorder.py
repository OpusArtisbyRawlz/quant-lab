"""
EvidenceRecorder — capture durable, auditable evidence from a finished experiment.

This is the sole writer of the ``evidence_event`` log (M11 PR-1). On a *finished*
experiment it reads the experiment ledger row, its regime label, and its
hypothesis-node link, assembles the full metric + provenance bundle, and appends
**one immutable evidence event** per evidence source.

It is deliberately a **capture-only** component:

  * it makes **no** promotion, retirement, confidence, or deployment decision;
  * it never mutates M7 / M9 / M10 records (it only reads them);
  * it is idempotent — re-recording the same ``(experiment_id, evidence_source)``
    is a no-op, so a re-run or crash-recovery reproduces identical evidence rows.

All decision logic (posterior updating, promotion, retirement, budgets) belongs to
later M11 PRs that *read* the evidence captured here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.storage.db import DB_PATH, get_connection
from agents.storage import evidence_store, ledger_store
from agents.storage.context_store import get_regime_label

# Versions stamped on captured evidence so a re-run under a newer methodology is
# distinguishable. Kept as plain constants (no statistics live in PR-1).
METHODOLOGY_VERSION = "m11-0"
STAT_METHOD_VERSION = "none"        # PR-1 captures raw evidence; no stats applied yet

# Numeric experiment-ledger columns copied verbatim into the metrics snapshot.
_METRIC_COLUMNS = (
    "sharpe", "mdd", "cagr", "vol", "calmar",
    "net_sharpe", "net_mdd", "net_cagr", "net_vol", "net_calmar",
    "turnover_annualized", "turnover_average_period",
    "transaction_cost_annualized", "slippage_annualized",
)

# Keys within an experiment's raw_metrics that carry Project 06 capacity /
# deployment measurements, captured where available.
_CAPACITY_KEYS = (
    "capacity", "capacity_usd", "capacity_shares", "adv_fraction",
    "deployment_capacity", "max_deployable", "liquidity_score",
    "days_to_liquidate", "capacity_metrics", "deployment_metrics",
)


def _loads(value: Any) -> Any:
    if value is None or isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


class EvidenceRecorder:
    """Append one durable evidence event per finished experiment (idempotent)."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path

    # -- hypothesis-node link (read-only; no M10 mutation) -----------------
    def _hypothesis_node(self, experiment_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM hypothesis_node WHERE experiment_id = ? LIMIT 1",
                (experiment_id,),
            ).fetchone()
        return dict(row) if row else None

    # -- capture -----------------------------------------------------------
    def record(
        self,
        experiment_id: str,
        *,
        evidence_source: str = evidence_store.SOURCE_IN_SAMPLE,
        dataset_id: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        capacity_metrics: Any = None,
        methodology_version: str = METHODOLOGY_VERSION,
        stat_method_version: str = STAT_METHOD_VERSION,
    ) -> int | None:
        """Capture evidence for a finished experiment.

        Returns the new ``evidence_event`` id, or ``None`` if evidence for this
        ``(experiment_id, evidence_source)`` was already captured (idempotent).
        Raises ``KeyError`` if the experiment does not exist in the ledger.
        """
        exp = ledger_store.get_experiment(experiment_id, db_path=self.db_path)
        if exp is None:
            raise KeyError(f"unknown experiment_id: {experiment_id!r}")

        raw_metrics = _loads(exp.get("raw_metrics")) or {}
        raw_metrics = raw_metrics if isinstance(raw_metrics, dict) else {}

        # Result-metrics snapshot: ledger numeric columns + native raw metrics.
        metrics: dict[str, Any] = {
            col: exp.get(col) for col in _METRIC_COLUMNS if exp.get(col) is not None
        }
        for k, v in raw_metrics.items():
            metrics.setdefault(k, v)

        # Capacity / deployment metrics from Project 06, where available. An
        # explicit argument wins; otherwise harvest known keys from raw_metrics.
        if capacity_metrics is None:
            harvested = {k: raw_metrics[k] for k in _CAPACITY_KEYS if k in raw_metrics}
            capacity_metrics = harvested or None

        # Hypothesis-node link (best-effort; None for ad-hoc experiments).
        node = self._hypothesis_node(experiment_id)
        hypothesis_id = node.get("node_id") if node else None
        campaign_id = node.get("campaign_id") if node else None

        feature_names = _loads(exp.get("features"))
        robustness_flags = _loads(exp.get("robustness_flags"))
        regime = get_regime_label(experiment_id, db_path=self.db_path)

        # Date range: explicit args win, else fall back to the ledger's date.
        exp_date = exp.get("date")
        date_start = date_start if date_start is not None else exp_date
        date_end = date_end if date_end is not None else exp_date

        return evidence_store.record_evidence(
            experiment_id,
            evidence_source=evidence_source,
            hypothesis_id=hypothesis_id,
            campaign_id=campaign_id,
            source_idea_id=exp.get("source_idea_id"),
            source_model=exp.get("source_model"),
            market=exp.get("market"),
            universe=exp.get("universe"),
            regime=regime,
            bar_type=exp.get("bar_type") or "time",
            feature_names=feature_names,
            dataset_id=dataset_id,
            date_start=date_start,
            date_end=date_end,
            methodology_version=methodology_version,
            stat_method_version=stat_method_version,
            metrics=metrics or None,
            robustness_flags=robustness_flags,
            capacity_metrics=capacity_metrics,
            critic_decision=exp.get("decision"),
            provenance={"project": exp.get("project"),
                        "experiment_type": exp.get("experiment_type"),
                        "status": exp.get("status")},
            db_path=self.db_path,
        )
