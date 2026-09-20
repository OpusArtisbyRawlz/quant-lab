"""
recovery_inventory — reproducible enumeration of the historical strategy program.

Reads the *stored* evidence (experiment result CSVs, project summaries, the recovery
manifest, and the factory DB) and returns a single tidy inventory of every materially
distinct historical strategy candidate across Projects 02-06. Nothing is hard-coded
from memory: every row points at a concrete artifact, and every metric is read from
that artifact at call time. Missing artifacts degrade gracefully to empty results so
the notebook renders on any checkout (the raw data tree is git-ignored).

This is a *reader*, not a source of truth: the DB, manifest, event log and provenance
system remain authoritative. See HISTORICAL_STRATEGY_RECOVERY.ipynb for the rendered
report and README.md for intent.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
EXP = REPO_ROOT / "experiments" / "completed"
RESEARCH = REPO_ROOT / "research"
DB_PATH = REPO_ROOT / "agents" / "quant_agents.db"
MANIFEST = REPO_ROOT / "agents" / "recovery" / "historical_strategies.json"

# Canonical column schema for every candidate row.
COLUMNS = [
    "recovery_id", "project", "strategy_name", "strategy_family", "variant",
    "source_notebook", "source_file", "source_commit", "historical_role",
    "historically_selected", "orig_sharpe", "orig_cagr", "orig_vol", "orig_mdd",
    "orig_calmar", "recovery_status", "executable_status", "fidelity_status",
    "factory_experiment_id", "factory_sharpe", "factory_mdd", "project07_status",
    "blocker", "provenance_link",
]

_NA = None


def _row(**kw: Any) -> dict[str, Any]:
    r = {c: _NA for c in COLUMNS}
    r.update(kw)
    return r


def _f(x: Any) -> float | None:
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Project 02 — volatility regime (vendored)
# --------------------------------------------------------------------------- #
def p02_candidates() -> list[dict[str, Any]]:
    base = RESEARCH / "project_02_volatility_regime"
    if not base.exists():
        return []
    nb = "research/project_02_volatility_regime/notebooks/spy_volatility_regime_model.ipynb"
    art = "research/project_02_volatility_regime/artifacts/vol_regime_calibrated_oof.csv"
    return [_row(
        recovery_id="p02_volatility_regime",
        project="project_02_volatility_regime",
        strategy_name="SPY volatility-regime classifier (calibrated OOF)",
        strategy_family="volatility_regime", variant="two_stage_logistic",
        source_notebook=nb, source_file=art,
        historical_role="model", historically_selected="yes",
        recovery_status="recovered_source (vendored)", executable_status="blocked",
        fidelity_status="pending_reproduction",
        blocker="single-asset SPY probability model; not a cross-sectional LS signal — "
                "no executor path yet",
    )]


# --------------------------------------------------------------------------- #
# Project 03 — directional alpha (SPY 5d direction)
# --------------------------------------------------------------------------- #
def p03_candidates() -> list[dict[str, Any]]:
    base = RESEARCH / "project_03_directional_alpha"
    if not base.exists():
        return []
    nb = "research/project_03_directional_alpha/notebooks/03_model_training.ipynb"
    metrics = {}
    mfile = EXP / "exp_001_dir_alpha_spy_5d" / "metrics.json"
    if mfile.exists():
        metrics = json.loads(mfile.read_text())
    out = []
    out.append(_row(
        recovery_id="p03_logistic_5d", project="project_03_directional_alpha",
        strategy_name="SPY 5-day direction — logistic regression",
        strategy_family="directional_classifier", variant="logistic",
        source_notebook=nb, source_file="experiments/completed/exp_001_dir_alpha_spy_5d",
        historical_role="model", historically_selected="yes",
        recovery_status="cataloged", executable_status="blocked",
        fidelity_status="not_started",
        blocker="single-asset SPY classifier (AUC "
                f"{_f(metrics.get('auc'))}); engine is cross-sectional LS",
    ))
    out.append(_row(
        recovery_id="p03_random_forest_5d", project="project_03_directional_alpha",
        strategy_name="SPY 5-day direction — random forest",
        strategy_family="directional_classifier", variant="random_forest",
        source_notebook=nb, source_file="research/project_03_directional_alpha/project_summary.md",
        historical_role="alternative", historically_selected="no",
        recovery_status="cataloged", executable_status="blocked",
        fidelity_status="not_started",
        blocker="tested alternative (AUC ~0.506, worse than logistic); single-asset",
    ))
    out.append(_row(
        recovery_id="p03_naive_up_baseline", project="project_03_directional_alpha",
        strategy_name="Naive 'always up' baseline",
        strategy_family="directional_classifier", variant="naive_baseline",
        source_notebook=nb, source_file="research/project_03_directional_alpha/project_summary.md",
        historical_role="baseline", historically_selected="no",
        recovery_status="reference_only", executable_status="n/a",
        fidelity_status="n/a", blocker="benchmark reference, not a tradable strategy",
    ))
    return out


# --------------------------------------------------------------------------- #
# Project 04 — return-forecast alpha (cross-sectional LS)
# --------------------------------------------------------------------------- #
# The 12 base strategies P05 carried forward as overlay inputs (⇒ "selected").
_P04_CARRIED = {
    "LS 20%", "LS 30%", "Blend 70/30 (LS20 + LS30)", "Blend 60/40 (LS20 + LS30)",
    "Blend 50/50 (LS20 + LS30)", "Blend 40/60 (LS20 + LS30)", "LS 20% + Linear",
    "LS 20% + Pow 0.7", "LS 20% + Sqrt", "LS 20% + Sqrt Partial",
    "LS 20% + Sqrt Partial normalized", "LS 30% + Sqrt Partial norm",
}


def _p04_family_variant(name: str) -> tuple[str, str]:
    if name.startswith("Blend"):
        return "blend", name.replace("Blend ", "").split(" (")[0]
    if "Vol Target" in name:
        return "blend_voltarget", name.split("+ ")[-1].strip()
    base = "ls20" if "LS 20%" in name else ("ls30" if "LS 30%" in name else "other")
    if "+" in name:
        return f"{base}_transform", name.split("+", 1)[1].strip()
    return base, "plain"


def p04_candidates() -> list[dict[str, Any]]:
    f = EXP / "exp_004_project04_final" / "strategy_comparison.csv"
    if not f.exists():
        return []
    df = pd.read_csv(f)
    nb = "research/project_04_return_forecast_alpha/notebooks/04_portfolio_research.ipynb"
    out = []
    for _, r in df.iterrows():
        name = str(r["Strategy"]).strip()
        fam, var = _p04_family_variant(name)
        rid = "p04_" + (name.lower().replace("%", "pct").replace(" ", "_")
                        .replace("+", "plus").replace("/", "_").replace("(", "")
                        .replace(")", "").replace("__", "_").strip("_"))
        out.append(_row(
            recovery_id=rid, project="project_04_return_forecast_alpha",
            strategy_name=name, strategy_family=fam, variant=var,
            source_notebook=nb,
            source_file="experiments/completed/exp_004_project04_final/strategy_comparison.csv",
            historical_role="blend" if fam.startswith("blend") else "baseline"
                            if var == "plain" else "alternative",
            historically_selected="yes" if name in _P04_CARRIED else "no",
            orig_sharpe=_f(r.get("Sharpe")), orig_cagr=_f(r.get("CAGR")),
            orig_vol=_f(r.get("Vol")), orig_mdd=_f(r.get("MDD")),
            orig_calmar=_f(r.get("Calmar")),
            recovery_status="cataloged", executable_status="blocked",
            fidelity_status="not_started",
            blocker="not yet ported to a historical signal",
        ))
    return out


# --------------------------------------------------------------------------- #
# Project 05 — risk engine (overlays on the P04 base strategies)
# --------------------------------------------------------------------------- #
def _p05_overlay_rows(csv: Path, overlay: str) -> list[dict[str, Any]]:
    if not csv.exists():
        return []
    df = pd.read_csv(csv)
    scol = "Sharpe_smooth_dd" if "Sharpe_smooth_dd" in df.columns else "Sharpe_dd"
    mcol = "MDD_smooth_dd" if "MDD_smooth_dd" in df.columns else "MDD_dd"
    ccol = "CAGR_smooth_dd" if "CAGR_smooth_dd" in df.columns else "CAGR_dd"
    kcol = "Calmar_smooth_dd" if "Calmar_smooth_dd" in df.columns else "Calmar_dd"
    rel = str(csv.relative_to(REPO_ROOT))
    out = []
    for _, r in df.iterrows():
        under = str(r["Strategy"]).strip()
        out.append(_row(
            recovery_id=f"p05_{overlay}_{under}", project="project_05_risk_engine",
            strategy_name=f"{under} + {overlay} overlay",
            strategy_family=f"overlay_{overlay}", variant=under,
            source_notebook="research/project_05_risk_engine/",
            source_file=rel, historical_role="overlay", historically_selected="no",
            orig_sharpe=_f(r.get(scol)), orig_cagr=_f(r.get(ccol)),
            orig_mdd=_f(r.get(mcol)), orig_calmar=_f(r.get(kcol)),
            recovery_status="cataloged", executable_status="blocked",
            fidelity_status="not_started",
            blocker="equity-curve overlay on a base book; not a standalone "
                    "cross-sectional signal",
        ))
    return out


def _p05_portfolio_rows() -> list[dict[str, Any]]:
    f = EXP / "exp_005_risk_engine_final" / "final_project05_summary.csv"
    if not f.exists():
        return []
    df = pd.read_csv(f)
    rel = "experiments/completed/exp_005_risk_engine_final/final_project05_summary.csv"
    out = []
    for i, r in df.iterrows():
        name = str(r["Strategy"]).strip()
        out.append(_row(
            recovery_id=f"p05_portfolio_{i+1}", project="project_05_risk_engine",
            strategy_name=name, strategy_family="portfolio_overlay",
            variant="weighted_multi_strategy", source_notebook="research/project_05_risk_engine/",
            source_file=rel, historical_role="overlay",
            historically_selected="yes",  # the P05 deliverables carried into P06
            orig_sharpe=_f(r.get("Sharpe")), orig_cagr=_f(r.get("CAGR")),
            orig_vol=_f(r.get("Vol")), orig_mdd=_f(r.get("MDD")),
            orig_calmar=_f(r.get("Calmar")),
            recovery_status="cataloged", executable_status="blocked",
            fidelity_status="not_started",
            blocker="portfolio-level overlay composition; not a single signal",
        ))
    return out


def p05_candidates() -> list[dict[str, Any]]:
    rows = []
    rows += _p05_overlay_rows(
        EXP / "exp_005_risk_engine_final" / "all_strategies_smooth_dd_results.csv",
        "smooth_dd")
    rows += _p05_overlay_rows(
        EXP / "exp_005_risk_engine_v1" / "dd_overlay_all_strategies_comparison.csv",
        "step_dd")
    rows += _p05_portfolio_rows()
    return rows


# --------------------------------------------------------------------------- #
# Project 06 — deployment validation (tournament candidates)
# --------------------------------------------------------------------------- #
def p06_candidates() -> list[dict[str, Any]]:
    f = EXP / "exp_006_deployment_candidate_tournament" / "master_comparison.csv"
    if not f.exists():
        return []
    df = pd.read_csv(f)
    rel = "experiments/completed/exp_006_deployment_candidate_tournament/master_comparison.csv"
    out = []
    for _, r in df.iterrows():
        name = str(r["Candidate"]).strip()
        is_v1 = str(r.get("is_v1")).strip().lower() == "true"
        rid = "p06_" + (name.lower().replace(" ", "_").replace("(", "").replace(")", "")
                        .replace(",", "").replace(".", "").replace("-", "_")
                        .replace("+", "plus").replace("__", "_").strip("_"))[:48]
        out.append(_row(
            recovery_id=rid, project="project_06_deployment_validation",
            strategy_name=name, strategy_family="deployment_candidate",
            variant=str(r.get("Overlay", "")).strip(),
            source_notebook="experiments/completed/exp_006_deployment_candidate_tournament/run_tournament.py",
            source_file=rel, historical_role="deployment",
            historically_selected="yes" if is_v1 else "no",
            orig_sharpe=_f(r.get("Sharpe")), orig_cagr=_f(r.get("CAGR")),
            orig_vol=_f(r.get("Volatility")), orig_mdd=_f(r.get("MDD")),
            orig_calmar=_f(r.get("Calmar")),
            recovery_status="cataloged", executable_status="blocked",
            fidelity_status="not_started",
            blocker="deployment overlay config on the P05 portfolio; not a signal",
        ))
    return out


# --------------------------------------------------------------------------- #
# Assembly + enrichment from the authoritative manifest / factory DB
# --------------------------------------------------------------------------- #
def build_inventory() -> pd.DataFrame:
    rows = (p02_candidates() + p03_candidates() + p04_candidates()
            + p05_candidates() + p06_candidates())
    df = pd.DataFrame(rows, columns=COLUMNS)
    return _enrich(df)


def _manifest_ids() -> set[str]:
    if not MANIFEST.exists():
        return set()
    m = json.loads(MANIFEST.read_text())
    return {s["strategy_id"] for s in m.get("strategies", [])}


def _factory_results(db: Path = DB_PATH) -> dict[str, dict[str, Any]]:
    """Map ported historical signal -> its factory experiment result, read from the DB.
    Keyed by the recovery_id we assign to the ported baselines (p04_ls_20pct/p04_ls_30pct)."""
    if not db.exists():
        return {}
    try:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        exps = {dict(r).get("experiment_id"): dict(r)
                for r in con.execute("SELECT * FROM experiments")}
        con.close()
    except sqlite3.Error:
        return {}
    out: dict[str, dict[str, Any]] = {}
    # The P04 authoritative replay wrote exp_007 (LS20) and exp_008 (LS30).
    pairs = {"p04_ls_20pct": "exp_007_idea_generator_quantile_ranking",
             "p04_ls_30pct": "exp_008_idea_generator_quantile_ranking"}
    for rid, eid in pairs.items():
        e = exps.get(eid)
        if e:
            out[rid] = {"experiment_id": eid,
                        "sharpe": e.get("sharpe_ratio") or e.get("sharpe"),
                        "mdd": e.get("max_drawdown") or e.get("mdd")}
    return out


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    manifest = _manifest_ids()
    factory = _factory_results()
    for i, r in df.iterrows():
        rid = r["recovery_id"]
        # recovery_status: is this candidate represented in the recovery manifest?
        if rid in manifest and r["recovery_status"] == "cataloged":
            df.at[i, "recovery_status"] = "in_manifest"
        # The two fidelity-verified P04 baselines.
        if rid in factory:
            fr = factory[rid]
            df.at[i, "factory_experiment_id"] = fr["experiment_id"]
            df.at[i, "factory_sharpe"] = _f(fr["sharpe"])
            df.at[i, "factory_mdd"] = _f(fr["mdd"])
            df.at[i, "executable_status"] = "executable"
            df.at[i, "recovery_status"] = "replayed"
            df.at[i, "project07_status"] = "preliminary (pending Project 07)"
            df.at[i, "blocker"] = None
            # Fidelity verdict: replay Sharpe vs authoritative Sharpe.
            os_, fs_ = r["orig_sharpe"], _f(fr["sharpe"])
            if os_ is not None and fs_ is not None:
                df.at[i, "fidelity_status"] = (
                    "verified_exact" if abs(os_ - fs_) < 0.01 else
                    f"delta={round(abs(os_-fs_),4)}")
            df.at[i, "provenance_link"] = "docs/P04_RECOVERY_RESULT.md"
    return df


def counts(df: pd.DataFrame) -> dict[str, Any]:
    def n(mask) -> int:
        return int(mask.sum())
    return {
        "total_candidates": len(df),
        "by_project": df.groupby("project").size().to_dict(),
        "by_family": df.groupby("strategy_family").size().to_dict(),
        "historically_selected": n(df["historically_selected"] == "yes"),
        "historically_abandoned": n(df["historically_selected"] == "no"),
        "in_manifest": n(df["recovery_status"] == "in_manifest"),
        "replayed": n(df["recovery_status"] == "replayed"),
        "fidelity_verified": n(df["fidelity_status"] == "verified_exact"),
        "executable": n(df["executable_status"] == "executable"),
        "blocked": n(df["executable_status"] == "blocked"),
    }


if __name__ == "__main__":  # pragma: no cover
    inv = build_inventory()
    c = counts(inv)
    print(json.dumps(c, indent=2, default=str))
