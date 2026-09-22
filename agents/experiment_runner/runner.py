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
from src.data.bars import BarEngine, align_cross_section
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
    # 5b. Bar sampling — hand raw data to the Bar Engine and continue with
    #     its output. The executor is deliberately bar-type-agnostic: it
    #     never branches on the clock and never imports a bar implementation.
    #     All dispatch/validation/construction lives inside BarEngine.build.
    #     ``spec.bar_type`` is a plain string; the engine coerces it to a
    #     SamplingSpec internally. In BE-1/identity mode this is a faithful
    #     pass-through, so results are byte-identical to the pre-engine path.
    # ------------------------------------------------------------------
    try:
        bar_result = BarEngine.build(data_dict, spec.bar_type)
    except Exception:
        err = traceback.format_exc()
        log.exception("Bar sampling failed for %s", experiment_id)
        write_error_txt(folder, err)
        _ingest_failed(folder, db_path)
        return RunResult(
            experiment_id=experiment_id,
            status="failed",
            artifact_path=folder,
            warnings=warnings,
            error=err,
        )
    #     Cross-sectional alignment onto a common grid. For gap-free daily time
    #     bars this is the identity (the production path stays byte-identical);
    #     for irregular event bars it forward-fills each ticker onto the union
    #     of bar-close timestamps so the peer-ranking pipeline still works. The
    #     executor applies it unconditionally — it is bar-agnostic and never
    #     inspects the clock to decide.
    data_dict = align_cross_section(bar_result.data)

    # ------------------------------------------------------------------
    # 6. Run backtest pipeline
    # ------------------------------------------------------------------
    try:
        metrics, variant_row = _run_pipeline(
            spec,
            data_dict,
            cost_config or CostConfig.load(),
            periods_per_year=bar_result.periods_per_year,
        )
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
    # ------------------------------------------------------------------
    # 7b. Deployment evaluation stage (general; runs AFTER execution, BEFORE the
    #     Project 07 hand-off). Reuses the composed portfolio base + the reusable
    #     src/analysis deployment battery/tournament. Records the deployment decision
    #     into metrics (so it is persisted + ingested) and writes the master
    #     comparison table into the experiment folder.
    # ------------------------------------------------------------------
    if getattr(spec, "deployment", None) and getattr(spec, "portfolio", None):
        try:
            metrics["deployment"] = _run_deployment_stage(
                spec, data_dict, folder, data_root)
        except Exception:
            err = traceback.format_exc()
            log.exception("Deployment stage failed for %s", experiment_id)
            warnings.append(f"Deployment stage warning: {err.splitlines()[-1]}")

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


def _apply_overlay(portfolio_returns, overlay: dict):
    """Apply a historical risk overlay to the gross portfolio return series.

    Reuses Project 05's authoritative implementation verbatim (``src/risk``); this
    function only dispatches. ``smooth_dd`` reproduces
    ``src.risk.allocation.compare_base_vs_dd_overlay``: equity → drawdown → smooth
    exposure ``floor + (1-floor)·exp(-k·|dd|)`` → lag-1 applied to returns.
    """
    method = (overlay or {}).get("method")
    if method in ("smooth_dd", "smooth_drawdown_exposure"):
        from src.risk import drawdown as dd
        equity = (1 + portfolio_returns).cumprod()
        drawdown = dd.compute_drawdown(equity)
        exposure = dd.drawdown_exposure_smooth(
            drawdown,
            floor=float(overlay.get("floor", 0.55)),
            k=float(overlay.get("k", 5)),
        )
        return dd.apply_exposure_to_return(portfolio_returns, exposure)
    if method == "vol_target":
        # Project 04 vol-targeting (notebook cells 195/198): scale by target/realised
        # vol, clipped, lagged one day. Realised vol = rolling std × √PPY.
        import numpy as np
        tv = float(overlay["target_vol"])
        lookback = int(overlay.get("lookback", 20))
        clip_upper = float(overlay.get("clip_upper", 2.0))
        realised = portfolio_returns.rolling(lookback).std() * np.sqrt(252)
        scaling = (tv / realised).clip(upper=clip_upper)
        return portfolio_returns * scaling.shift(1)
    raise ValueError(f"Unknown overlay method: {method!r}")


def _run_deployment_stage(spec: ExperimentSpec, data_dict, folder, data_root) -> dict:
    """Run the reusable deployment tournament on the composed base and persist it.

    Returns the deployment decision dict (recorded in metrics); writes
    ``master_comparison.csv`` + ``deployment_decision.json`` into the experiment folder.
    """
    from agents.experiment_runner.deployment_stage import run_deployment_tournament
    import json as _json
    cfg = spec.deployment
    repo_root = data_root.parent.parent  # data_root is <repo>/data/raw
    v2_rel = cfg.get("v2_source") or (
        "experiments/completed/exp_005_risk_engine_final/final_returns_v2_with_dates.csv")
    v2_source = Path(v2_rel) if Path(v2_rel).is_absolute() else repo_root / v2_rel
    adv_dir = data_root / cfg.get("adv_universe", "project_04_universe")
    comp, decision = run_deployment_tournament(
        spec.portfolio, data_dict, v2_source=v2_source, adv_data_dir=adv_dir)
    comp.to_csv(folder / "master_comparison.csv", index=False)
    (folder / "deployment_decision.json").write_text(_json.dumps(decision, indent=2, default=float))
    return decision


def _child_return_stream(child: dict, base_panel, periods_per_year) -> "pd.Series":
    """Return one child's gross return stream, computed through the SAME pipeline.

    Leaf child: apply its signal combo → optional weight-level overlay → portfolio
    returns. Nested child: recursively compose its own children. Either way, an
    optional per-child return-level overlay is applied last. No child signal is
    recomputed here — leaf books reuse ``apply_signal_combo``/``_portfolio_returns``.
    """
    from src.portfolio.composite import combine_returns
    nested = child.get("portfolio")
    if nested:
        sub = [
            (c["child_id"], _child_return_stream(c, base_panel, periods_per_year), c["weight"])
            for c in sorted(nested["children"], key=lambda x: x["child_id"])
        ]
        ret = combine_returns(sub)
        if nested.get("overlay"):
            ret = _apply_overlay(ret, nested["overlay"])
    else:
        panel = apply_signal_combo(base_panel, signal_names=child["features"])
        if child.get("weight_overlay"):
            from src.risk.weight_overlay import apply_weight_overlay
            panel = apply_weight_overlay(panel, child["weight_overlay"])
        ret = _portfolio_returns(panel)
    if child.get("overlay"):
        ret = _apply_overlay(ret, child["overlay"])
    return ret


def _run_portfolio_pipeline(spec: ExperimentSpec, data_dict, periods_per_year):
    """Compose a multi-strategy portfolio from child return streams and build metrics.

    The children execute through the normal pipeline (``_child_return_stream``); this
    layer only weights, combines (deterministic child order), and applies the
    portfolio-level overlay. Composite metrics are gross (the historical multi-strategy
    portfolios are gross); net/turnover are not separately modelled for a composite and
    are recorded as None rather than fabricated.
    """
    from src.portfolio.composite import PortfolioSpec, combine_returns
    from agents.experiment_runner.metrics_writer import compute_metrics

    pf = PortfolioSpec.from_dict(spec.portfolio)
    pf.validate()
    base_panel = run_market_alpha_pipeline(data_dict)

    streams = [
        (c.child_id, _child_return_stream(_child_to_dict(c), base_panel, periods_per_year), c.weight)
        for c in pf.ordered_children()
    ]
    portfolio_returns = combine_returns(streams)
    if pf.overlay:
        portfolio_returns = _apply_overlay(portfolio_returns, pf.overlay)

    gross = dict(compute_metrics(portfolio_returns, periods_per_year))
    metrics = dict(gross)
    # Composite costs are not separately modelled (historical portfolios are gross);
    # record net == gross and null turnover/cost rather than inventing figures.
    metrics["net"] = dict(gross)
    for k in ("turnover_annualized", "turnover_average_period",
              "transaction_cost_annualized", "slippage_annualized", "cost_drag_annualized"):
        metrics[k] = None
    metrics["robustness"] = {"subperiod_sharpes": [], "parameter_sensitivity": {}}
    metrics["robustness_flags"] = {}

    variant_row = {
        "Strategy": pf.portfolio_id,
        "Sharpe": gross.get("sharpe"), "MDD": gross.get("mdd"),
        "CAGR": gross.get("cagr"), "Vol": gross.get("vol"), "Calmar": gross.get("calmar"),
        "Net Sharpe": gross.get("sharpe"), "Net MDD": gross.get("mdd"),
    }
    return metrics, variant_row


def _child_to_dict(c) -> dict:
    """PortfolioChild → the plain dict shape _child_return_stream consumes."""
    return {
        "child_id": c.child_id, "weight": c.weight, "features": c.features,
        "portfolio": c.portfolio.to_dict() if c.portfolio else None,
        "overlay": c.overlay, "weight_overlay": c.weight_overlay,
    }


def _run_pipeline(
    spec: ExperimentSpec,
    data_dict: dict[str, pd.DataFrame],
    cost_config: CostConfig,
    *,
    periods_per_year: float | None = None,
) -> tuple[dict, dict]:
    """
    Build the panel, apply signal combo, compute gross + net metrics, turnover,
    costs, and robustness checks. Return the full metric bundle and a
    strategy_comparison row.

    ``periods_per_year`` is the annualisation cadence for the sampled bars,
    supplied by the Bar Engine (``BarResult.periods_per_year``). For daily time
    bars this is 252 — identical to the historical default — so time-bar runs
    are unchanged; event bars carry their realised cadence instead. The executor
    stays bar-agnostic: it forwards a single float and never inspects the clock.
    When ``None`` the cost-config cadence is used (backwards-compatible default).

    Returns
    -------
    (metrics_dict, variant_row_dict)
    """
    if periods_per_year is None:
        periods_per_year = cost_config.periods_per_year

    # Multi-strategy composite portfolio (default None ⇒ single-strategy path below,
    # byte-for-byte unchanged). Children execute through this same pipeline.
    if getattr(spec, "portfolio", None):
        return _run_portfolio_pipeline(spec, data_dict, periods_per_year)

    # Build panel with features and forward returns
    base_panel = run_market_alpha_pipeline(data_dict)

    # Apply multi-signal combo (works for single signals too)
    panel = apply_signal_combo(base_panel, signal_names=spec.features)

    # Gross daily portfolio returns
    portfolio_returns = _portfolio_returns(panel)

    # Historical recovery (Project 05): optional risk overlay on the portfolio return
    # series. Path-dependent (reads the book's own drawdown), so it runs here — after
    # the cross-sectional book is built — reusing the authoritative src/risk code. No
    # overlay ⇒ unchanged behaviour.
    if getattr(spec, "overlay", None):
        portfolio_returns = _apply_overlay(portfolio_returns, spec.overlay)

    # Gross + net + turnover/cost bundle (preserves flat gross keys)
    metrics = build_metric_bundle(
        panel,
        portfolio_returns,
        cost_config,
        periods_per_year=periods_per_year,
    )

    # ── Robustness: subperiod stability + parameter sensitivity ───────────
    net_block = metrics.get("net", {})
    sensitivity = parameter_sensitivity(
        base_panel,
        spec.features,
        _portfolio_returns,
        cost_config,
        periods_per_year=periods_per_year,
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
        periods_per_year=periods_per_year,
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
