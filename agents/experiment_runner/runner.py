"""
runner.py — public API for Milestone 3 experiment execution.

Takes an ExperimentSpec, runs the backtest pipeline, writes the artifact
folder, and ingests the result into SQLite. Returns a RunResult regardless
of outcome — failures are recorded, not silently discarded.

Import boundary
---------------
Only modules inside agents/experiment_runner/ may import from src/.
Decision-making agents call run_experiment() but never import src/ directly.

Multi-variant design
---------------------
For Milestone 3, one spec produces one variant (one row in
strategy_comparison.csv). The folder schema already supports multiple rows
so a param_grid extension can be added without schema changes.

Data injection
--------------
Pass ``data_dict`` to skip the disk-loading step. This is the primary
testing seam — tests supply synthetic DataFrames and never call yfinance
or read from data/raw/.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from agents.protocol import ExperimentSpec
from agents.storage.db import DB_PATH
from agents.quant_interface.ingestion import ingest_one

from agents.experiment_runner.spec_validator import validate_spec
from agents.experiment_runner.data_loader import load_data, DataBundle
from agents.experiment_runner.folder_writer import (
    make_experiment_id,
    create_experiment_folder,
    write_config_json,
    write_results_summary,
    write_error_txt,
)
from agents.experiment_runner.metrics_writer import (
    compute_metrics,
    write_metrics_json,
    write_strategy_csv,
)
from agents.experiment_runner.cost_model import CostConfig
from agents.experiment_runner.net_metrics import build_metric_bundle
from agents.experiment_runner.robustness import (
    parameter_sensitivity,
    build_robustness_report,
)

# src/ imports — permitted only inside experiment_runner
from src.pipelines.cross_sectional import run_market_alpha_pipeline
from src.signals.combine import apply_signal_combo

log = logging.getLogger(__name__)

COMPLETED_DIR = Path(__file__).parent.parent.parent / "experiments" / "completed"
DATA_ROOT     = Path(__file__).parent.parent.parent / "data" / "raw"


@dataclass
class RunResult:
    experiment_id: str
    status: str                         # success / failed / invalid_spec / dry_run
    metrics: dict = field(default_factory=dict)
    artifact_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def run_experiment(
    spec: ExperimentSpec,
    *,
    db_path: Path = DB_PATH,
    completed_dir: Path = COMPLETED_DIR,
    data_root: Path = DATA_ROOT,
    data_dict: dict[str, pd.DataFrame] | None = None,
    dry_run: bool = False,
    cost_config: CostConfig | None = None,
) -> RunResult:
    """
    Execute a single experiment and persist the results.

    Parameters
    ----------
    spec : ExperimentSpec
        Fully-specified experiment. spec.experiment_id may be pre-set; if
        blank it is auto-assigned from the folder sequence.
    db_path : Path
        SQLite database path.
    completed_dir : Path
        Root of experiments/completed/.
    data_root : Path
        Root of data/raw/ for data loading.
    data_dict : dict, optional
        Pre-loaded market data. If supplied, the disk loading step is
        skipped. Primary testing seam — never calls yfinance.
    dry_run : bool
        If True, validate and optionally load data but do not write any
        files, run the backtest, or touch the database.

    Returns
    -------
    RunResult
        Always returned. Check .status and .error.
        status values:
          "success"      — backtest ran, files written, DB ingested
          "failed"       — backtest error; partial folder + error.txt written
          "invalid_spec" — validation failed; nothing written
          "dry_run"      — validation passed; nothing written (dry_run=True)
    """
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # 1. Validate spec
    # ------------------------------------------------------------------
    validation = validate_spec(
        spec,
        data_root=data_root,
        completed_dir=completed_dir,
        skip_data_check=(data_dict is not None),
    )
    warnings.extend(validation.warnings)

    if not validation.valid:
        return RunResult(
            experiment_id=spec.experiment_id or "(unassigned)",
            status="invalid_spec",
            error="; ".join(validation.errors),
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 2. Assign experiment ID
    # ------------------------------------------------------------------
    experiment_id = make_experiment_id(spec, completed_dir)
    spec.experiment_id = experiment_id  # write back so ingest picks it up

    # ------------------------------------------------------------------
    # 3. Dry-run exit
    # ------------------------------------------------------------------
    if dry_run:
        log.info("Dry run for %s — validation passed, no files written.", experiment_id)
        return RunResult(
            experiment_id=experiment_id,
            status="dry_run",
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 4. Create folder and write config.json immediately.
    #    Any subsequent failure can then write error.txt into this folder.
    # ------------------------------------------------------------------
    try:
        folder = create_experiment_folder(experiment_id, completed_dir)
    except FileExistsError:
        warnings.append(f"Folder {experiment_id} already exists — reusing.")
        folder = completed_dir / experiment_id

    write_config_json(folder, spec, experiment_id)

    # ------------------------------------------------------------------
    # 5. Load data (skip if caller supplied data_dict)
    # ------------------------------------------------------------------
    if data_dict is None:
        bundle: DataBundle = load_data(data_root / spec.universe)
        warnings.extend(bundle.warnings)
        if not bundle.data_dict:
            err = f"No data loaded from {data_root / spec.universe}"
            write_error_txt(folder, err)
            _ingest_failed(folder, db_path)
            return RunResult(
                experiment_id=experiment_id,
                status="failed",
                artifact_path=folder,
                warnings=warnings,
                error=err,
            )
        data_dict = bundle.data_dict

    # ------------------------------------------------------------------
    # 6. Run backtest pipeline
    # ------------------------------------------------------------------
    try:
        metrics, variant_row = _run_pipeline(spec, data_dict, cost_config or CostConfig.load())
    except Exception:
        err = traceback.format_exc()
        log.exception("Pipeline failed for %s", experiment_id)
        write_error_txt(folder, err)
        _ingest_failed(folder, db_path)
        return RunResult(
            experiment_id=experiment_id,
            status="failed",
            artifact_path=folder,
            warnings=warnings,
            error=err,
        )

    # ------------------------------------------------------------------
    # 7. Write result artifacts
    # ------------------------------------------------------------------
    write_metrics_json(metrics, folder)
    write_strategy_csv([variant_row], folder)
    write_results_summary(folder, metrics, spec, experiment_id)

    # ------------------------------------------------------------------
    # 8. Ingest into SQLite
    # ------------------------------------------------------------------
    ingest_result = ingest_one(folder, db_path=db_path)
    if ingest_result.status == "failed":
        warnings.append(f"Ingest warning: {ingest_result.error}")

    log.info(
        "%s completed — sharpe=%.3f  mdd=%.3f  variants=%d",
        experiment_id,
        metrics.get("sharpe") or float("nan"),
        metrics.get("mdd") or float("nan"),
        ingest_result.variants_written,
    )

    return RunResult(
        experiment_id=experiment_id,
        status="success",
        metrics=metrics,
        artifact_path=folder,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internal — pipeline execution
# ---------------------------------------------------------------------------

def _portfolio_returns(panel: pd.DataFrame) -> pd.Series:
    """
    Daily gross portfolio returns from weights × forward return.

    Uses fwd_ret_5 (the default horizon from run_market_alpha_pipeline).  This
    is the single place the forward-return column name is referenced, so the
    robustness sensitivity grid stays consistent with the main backtest.
    """
    return (
        (panel["weight"] * panel["fwd_ret_5"])
        .groupby(panel["Date"])
        .sum()
    )


def _run_pipeline(
    spec: ExperimentSpec,
    data_dict: dict[str, pd.DataFrame],
    cost_config: CostConfig,
) -> tuple[dict, dict]:
    """
    Build the panel, apply signal combo, compute gross + net metrics, turnover,
    costs, and robustness checks. Return the full metric bundle and a
    strategy_comparison row.

    Returns
    -------
    (metrics_dict, variant_row_dict)
    """
    # Build panel with features and forward returns
    base_panel = run_market_alpha_pipeline(data_dict)

    # Apply multi-signal combo (works for single signals too)
    panel = apply_signal_combo(base_panel, signal_names=spec.features)

    # Gross daily portfolio returns
    portfolio_returns = _portfolio_returns(panel)

    # Gross + net + turnover/cost bundle (preserves flat gross keys)
    metrics = build_metric_bundle(
        panel,
        portfolio_returns,
        cost_config,
        periods_per_year=cost_config.periods_per_year,
    )

    # ── Robustness: subperiod stability + parameter sensitivity ───────────
    net_block = metrics.get("net", {})
    sensitivity = parameter_sensitivity(
        base_panel,
        spec.features,
        _portfolio_returns,
        cost_config,
        periods_per_year=cost_config.periods_per_year,
    )
    # Net return series for subperiod analysis (recompute from costs once).
    from agents.experiment_runner.cost_model import compute_turnover, apply_costs
    net_returns, _, _ = apply_costs(
        portfolio_returns, compute_turnover(panel), cost_config
    )
    robustness = build_robustness_report(
        net_returns=net_returns,
        gross_sharpe=metrics.get("sharpe"),
        net_sharpe=net_block.get("sharpe"),
        sensitivity=sensitivity,
        periods_per_year=cost_config.periods_per_year,
    )
    metrics["robustness"] = {
        "subperiod_sharpes": robustness["subperiod_sharpes"],
        "parameter_sensitivity": robustness["parameter_sensitivity"],
    }
    metrics["robustness_flags"] = robustness["robustness_flags"]

    # One variant row per run; net columns added for traceability
    signal_combo_str = " + ".join(spec.features)
    variant_row = {
        "Strategy":      signal_combo_str,
        "Sharpe":        metrics.get("sharpe"),
        "MDD":           metrics.get("mdd"),
        "CAGR":          metrics.get("cagr"),
        "Vol":           metrics.get("vol"),
        "Calmar":        metrics.get("calmar"),
        "NetSharpe":     net_block.get("sharpe"),
        "NetMDD":        net_block.get("mdd"),
        "NetCAGR":       net_block.get("cagr"),
        "NetCalmar":     net_block.get("calmar"),
        "Turnover":      metrics.get("turnover_annualized"),
        "TxCost":        metrics.get("transaction_cost_annualized"),
        "Signal Combo":  signal_combo_str,
    }

    return metrics, variant_row


def _ingest_failed(folder: Path, db_path: Path) -> None:
    """Ingest a partial folder so a failed experiment row appears in the DB."""
    try:
        ingest_one(folder, db_path=db_path)
    except Exception:
        log.exception("Could not ingest failed experiment folder %s", folder)
