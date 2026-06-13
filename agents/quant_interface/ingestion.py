"""
Ingestion — scans experiments/completed/ and loads all artifact data into SQLite.

Design principles:
- Resilient: each experiment folder is processed independently; one failure
  does not abort the others.
- Idempotent: safe to run multiple times. Experiments and variants are upserted,
  not duplicated.
- Non-opinionated: strategy variants are stored as-is from the CSV.
  Promotion to signal_library requires an explicit human/agent decision.
- Transparent: every decision (skipped, ingested, partial, failed) is recorded
  in the returned IngestReport.

What is ingested per experiment folder:
  experiments table     ← experiment_id, artifact_path, status, best metrics
  strategy_variants     ← one row per strategy_comparison.csv / final_summary row
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.storage.db import get_connection, create_all_tables, DB_PATH
from agents.storage.ledger_store import upsert_experiment
from agents.quant_interface.artifact_reader import (
    ArtifactBundle,
    StrategyVariant,
    read_experiment_artifact,
)

log = logging.getLogger(__name__)

COMPLETED_DIR = Path(__file__).parent.parent.parent / "experiments" / "completed"

# Folders inside completed/ that are not experiment directories
_SKIP_NAMES = {"archive", ".DS_Store"}


@dataclass
class ExperimentIngestResult:
    experiment_id: str
    status: str                   # ingested / skipped / failed
    variants_written: int = 0
    bundle_warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class IngestReport:
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    total_variants: int = 0
    results: list[ExperimentIngestResult] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            f"Ingestion complete: {self.ingested} ingested, "
            f"{self.skipped} skipped, {self.failed} failed, "
            f"{self.total_variants} strategy variants written."
        ]
        for r in self.results:
            tag = {"ingested": "✓", "skipped": "–", "failed": "✗"}.get(r.status, "?")
            line = f"  {tag} {r.experiment_id}"
            if r.variants_written:
                line += f" ({r.variants_written} variants)"
            if r.error:
                line += f" ERROR: {r.error}"
            if r.bundle_warnings:
                line += f" [{len(r.bundle_warnings)} warning(s)]"
            lines.append(line)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_all_completed(
    completed_dir: Path = COMPLETED_DIR,
    db_path: Path = DB_PATH,
) -> IngestReport:
    """
    Walk experiments/completed/, read every subfolder, and upsert into SQLite.

    Subfolders named in _SKIP_NAMES (e.g. 'archive') are skipped silently.
    Empty bundles (no readable files) are recorded as 'skipped'.
    All other outcomes (partial or full) are recorded as 'ingested'.
    """
    create_all_tables(db_path)
    report = IngestReport()

    if not completed_dir.exists():
        log.warning("Completed experiments directory not found: %s", completed_dir)
        return report

    dirs = sorted(
        d for d in completed_dir.iterdir()
        if d.is_dir() and d.name not in _SKIP_NAMES
    )

    for exp_dir in dirs:
        result = ingest_one(exp_dir, db_path=db_path)
        report.results.append(result)
        if result.status == "ingested":
            report.ingested += 1
            report.total_variants += result.variants_written
        elif result.status == "skipped":
            report.skipped += 1
        else:
            report.failed += 1

    return report


def ingest_one(
    exp_dir: Path,
    db_path: Path = DB_PATH,
) -> ExperimentIngestResult:
    """
    Read and ingest a single experiment folder.

    Returns an ExperimentIngestResult regardless of outcome.
    """
    exp_id = exp_dir.name
    result = ExperimentIngestResult(experiment_id=exp_id, status="skipped")

    try:
        bundle = read_experiment_artifact(exp_dir)
        result.bundle_warnings = bundle.warnings

        if bundle.is_empty:
            log.debug("No readable files in %s — skipping.", exp_id)
            return result

        # Write experiment row
        _upsert_from_bundle(bundle, db_path)

        # Write strategy variants
        variants_written = _upsert_variants(bundle, db_path)
        result.variants_written = variants_written

        result.status = "ingested"
        if bundle.warnings:
            log.debug(
                "%s ingested with %d warning(s): %s",
                exp_id, len(bundle.warnings), "; ".join(bundle.warnings),
            )

    except Exception as exc:
        result.status = "failed"
        result.error = str(exc)
        log.exception("Failed to ingest experiment folder %s", exp_dir)

    return result


# ---------------------------------------------------------------------------
# Strategy variant store helpers
# ---------------------------------------------------------------------------

def get_variants_for_experiment(
    experiment_id: str,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Return all strategy variants linked to an experiment."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM strategy_variants WHERE experiment_id = ? ORDER BY sharpe DESC NULLS LAST",
            (experiment_id,),
        ).fetchall()
        return [_deserialize_variant(dict(r)) for r in rows]


def get_unpromoted_variants(db_path: Path = DB_PATH) -> list[dict]:
    """Return variants not yet reviewed for signal library promotion."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM strategy_variants WHERE promoted_to_library = 0 "
            "ORDER BY sharpe DESC NULLS LAST"
        ).fetchall()
        return [_deserialize_variant(dict(r)) for r in rows]


def mark_variant_promoted(
    experiment_id: str,
    strategy_name: str,
    db_path: Path = DB_PATH,
) -> None:
    """Record that a variant has been promoted to the signal library."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE strategy_variants SET promoted_to_library = 1 "
            "WHERE experiment_id = ? AND strategy_name = ?",
            (experiment_id, strategy_name),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _upsert_from_bundle(bundle: ArtifactBundle, db_path: Path) -> None:
    """Build an experiment record from a bundle and upsert it."""
    record: dict[str, Any] = {
        "experiment_id":   bundle.experiment_id,
        "artifact_path":   str(bundle.artifact_path),
        "status":          "completed",
        "experiment_type": bundle.experiment_type,
    }

    # Always store raw metrics as-is — regardless of experiment type
    if bundle.metrics:
        record["raw_metrics"] = json.dumps(bundle.metrics)

    # Type-aware structured metric extraction
    exp_type = bundle.experiment_type or "unknown"

    if exp_type in ("portfolio", "risk_overlay", "unknown"):
        # Map standard portfolio/overlay metrics into dedicated columns
        _extract_portfolio_metrics(bundle, record)

    # For classification and regression: structured metrics live in raw_metrics only.
    # Named columns (sharpe, mdd, etc.) remain NULL — do not force a mapping.

    # If no sharpe yet and strategy_variants exist, fall back to best variant
    if record.get("sharpe") is None and bundle.strategy_variants:
        best = _best_variant(bundle.strategy_variants)
        if best:
            record.update({
                "sharpe":  best.sharpe,
                "mdd":     best.mdd,
                "cagr":    best.cagr,
                "vol":     best.vol,
                "calmar":  best.calmar,
            })

    # Pull model from config if available
    if bundle.config:
        for key in ("model", "final_model"):
            if key in bundle.config:
                record["model"] = str(bundle.config[key])
                break

    # Attach summary text (truncated for the DB column)
    if bundle.summary_text:
        record["result_summary"] = bundle.summary_text[:2000]

    upsert_experiment(record, db_path=db_path)


def _extract_portfolio_metrics(bundle: ArtifactBundle, record: dict[str, Any]) -> None:
    """
    Extract sharpe/mdd/cagr/vol/calmar from metrics dict into named columns.
    Only called for portfolio and risk_overlay experiment types.
    """
    if not bundle.metrics:
        return
    m = bundle.metrics
    _pick(m, record, "sharpe",  ["sharpe",  "Sharpe"])
    _pick(m, record, "mdd",     ["mdd",     "MDD",  "max_drawdown"])
    _pick(m, record, "cagr",    ["cagr",    "CAGR"])
    _pick(m, record, "vol",     ["vol",     "Vol",  "volatility"])
    _pick(m, record, "calmar",  ["calmar",  "Calmar"])


def _pick(
    src: dict[str, Any],
    dst: dict[str, Any],
    col: str,
    candidates: list[str],
) -> None:
    """Copy the first matching key from src into dst[col] as a float."""
    for key in candidates:
        if key in src:
            val = _to_float(src[key])
            if val is not None:
                dst[col] = val
            return


def _upsert_variants(bundle: ArtifactBundle, db_path: Path) -> int:
    """Upsert strategy variants — UNIQUE(experiment_id, strategy_name)."""
    if not bundle.strategy_variants:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    written = 0

    with get_connection(db_path) as conn:
        for v in bundle.strategy_variants:
            extra_json = json.dumps(v.extra) if v.extra else None
            conn.execute(
                """
                INSERT INTO strategy_variants
                    (experiment_id, strategy_name, sharpe, mdd, cagr, vol,
                     calmar, avg_exposure, extra_metrics, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id, strategy_name) DO UPDATE SET
                    sharpe        = excluded.sharpe,
                    mdd           = excluded.mdd,
                    cagr          = excluded.cagr,
                    vol           = excluded.vol,
                    calmar        = excluded.calmar,
                    avg_exposure  = excluded.avg_exposure,
                    extra_metrics = excluded.extra_metrics
                """,
                (
                    bundle.experiment_id,
                    v.strategy_name,
                    v.sharpe,
                    v.mdd,
                    v.cagr,
                    v.vol,
                    v.calmar,
                    v.avg_exposure,
                    extra_json,
                    now,
                ),
            )
            written += 1
        conn.commit()

    return written


def _best_variant(variants: list[StrategyVariant]) -> StrategyVariant | None:
    with_sharpe = [v for v in variants if v.sharpe is not None]
    if not with_sharpe:
        return None
    return max(with_sharpe, key=lambda v: v.sharpe)  # type: ignore[arg-type]


def _to_float(val: Any) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _deserialize_variant(record: dict[str, Any]) -> dict[str, Any]:
    if "extra_metrics" in record and isinstance(record["extra_metrics"], str):
        try:
            record["extra_metrics"] = json.loads(record["extra_metrics"])
        except (json.JSONDecodeError, TypeError):
            record["extra_metrics"] = {}
    return record
