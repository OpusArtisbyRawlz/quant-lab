"""
exp_006 — Deployment Candidate Tournament
=========================================

Determine the strongest *deployable* strategy in the repository by running every
serious deployment candidate through one identical validation battery and
letting the evidence rank them. No candidate is privileged for having been
shipped, for originating in a notebook, or for coming from the robustness branch.

Candidate groups
----------------
A. Deployment Candidate V1 (current baseline) — the shipped exp_005 dual-layer
   smooth-DD product. Has a full position book (20-name megacap universe).

B. Deployment-base challengers — robustness-notebook overlays re-applied to the
   *recovered deployment base* (strip the incumbent's outermost portfolio
   exposure, re-apply one overlay). Same universe, same book machinery, so the
   full capacity / turnover / transaction-cost battery is defined.

C. Historical low-MDD challengers — the robustness-notebook overlays applied to
   the historical `final_returns_v2_with_dates.csv` series, reproduced *exactly*
   as in 05_robustness_checks.ipynb. These are a **return-only** research series:
   there is no position book / universe mapping, so book-dependent battery
   stages (per-name market impact / capacity, book turnover, rebalance grid)
   are NOT EVALUABLE. That is recorded as a deployment deficiency, not waived.

Everything book-independent (performance, full risk battery incl. Sortino /
Ulcer / drawdown-duration / recovery, subperiod, regime, rolling, Monte-Carlo /
block bootstrap, parameter sensitivity, walk-forward, leakage) is run on every
candidate. Book-dependent stages are run where a book exists and marked N/A
otherwise.

Outputs (under this folder)
---------------------------
candidates/<slug>/    per-candidate: config.json, metrics.json, provenance.json,
                      equity_curve.csv, drawdown_curve.csv, exposure.csv,
                      rolling_metrics.csv, and (book candidates) turnover.csv,
                      txcost_stress.csv, capacity.csv, rebalance.csv,
                      operational_stress.csv
master_comparison.csv         the ranked master table (full column set)
tournament_config.json        global provenance + git hash + roster
(significance_vs_v1.csv and walk_forward_stability.csv are written by the
 companion scripts tournament_significance.py / tournament_stability.py)
"""

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PROJECT_ROOT))

from src.risk.drawdown import (
    compute_drawdown,
    drawdown_exposure_smooth,
    apply_exposure_to_return,
)
from src.analysis.turnover import compute_turnover
from src.analysis.deployment import transaction_cost_stress, rebalance_analysis
from src.analysis.deployment_stress import (
    capacity_analysis,
    operational_stress_tests,
)
from src.analysis.liquidity import (
    load_price_volume,
    daily_dollar_volume,
    average_daily_volume,
    capacity_ceiling,
)
from src.analysis.rolling import rolling_metrics
from src.utils.metrics import (
    sharpe_ratio,
    sortino_ratio,
    max_drawdown,
    annualized_return,
    annualized_volatility,
    ulcer_index,
    drawdown_stats,
)

HERE = Path(__file__).resolve().parent
CAND_DIR = HERE / "candidates"
EXP5 = PROJECT_ROOT / "experiments/completed/exp_005_risk_engine_final"

TX_COSTS = [0, 2, 5, 10, 20, 50]
REBAL_FREQS = [1, 5, 10, 21]
CAPITAL_LEVELS = [1e4, 5e4, 1e5, 5e5, 1e6, 5e6]
PARTICIPATION_CAP = 0.10
COST_ADJ_BPS = 10.0
PPY = 252
DD_THRESHOLD = 0.05


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT)
        ).decode().strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------
def load_deployment_base():
    """Recover the shared pre-portfolio-overlay base + incumbent book (Group A/B)."""
    dep = pd.read_csv(EXP5 / "final_weighted_multi_strategy_portfolio_dd.csv")
    w = pd.read_csv(EXP5 / "final_daily_weights.csv", parse_dates=["Date"])
    wide = w.pivot_table(index="Date", columns="Ticker", values="Weight").sort_index()
    assert len(dep) == len(wide)
    dates = wide.index
    dep.index = dates
    pr = dep["portfolio_return"].astype(float)
    exp = dep["portfolio_dd_exposure"].astype(float)
    base_ret = pr / exp.shift(1).fillna(1.0)
    base_book = wide.div(exp, axis=0)
    return base_ret, base_book, pr, exp, wide, dates


def load_historical_base():
    """The robustness-branch v2 series (Group C). Return-only, no book."""
    df = pd.read_csv(EXP5 / "final_returns_v2_with_dates.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df["returns"].astype(float)


def vol_multiplier(base_ret, window=252):
    rv = base_ret.rolling(window).std() * np.sqrt(PPY)
    m = (rv / rv.mean()) ** 0.5
    return m.clip(0.7, 1.3)


# ---------------------------------------------------------------------------
# Candidate roster
# ---------------------------------------------------------------------------
def build_candidates():
    base_ret, base_book, pr, exp, wide, dates = load_deployment_base()
    v2 = load_historical_base()
    assert (v2.index == dates).all(), "v2 dates must align with deployment dates"

    dep_dd = compute_drawdown((1 + base_ret).cumprod())
    dep_m = vol_multiplier(base_ret)

    def dep_overlay(e):
        return pd.Series(e, index=dates).fillna(1.0)

    v2_eq = (1 + v2).cumprod()
    v2_dd = compute_drawdown(v2_eq)
    v2_m = vol_multiplier(v2)

    cands = []

    # ---- Group A: V1 baseline (shipped, has book) ----
    cands.append(dict(
        slug="candidate_v1_baseline", name="Deployment Candidate V1 (baseline)",
        group="A — V1 baseline", source="exp_005_risk_engine_final (as shipped)",
        version="V1", overlay="dual-layer smooth-DD (strategy+portfolio, k5 floor0.55)",
        is_v1=True, has_book=True,
        ret=pr.copy(), book=wide.copy(), exposure=exp.copy(),
    ))

    # ---- Group B: deployment-base challengers (have book) ----
    groupB = [
        ("candidate_dd_only", "DD Only (floor0.3,k5)",
         "smooth DD floor0.3 k5, no vol, no clip", dep_overlay(drawdown_exposure_smooth(dep_dd, 0.3, 5))),
        ("candidate_combined", "Combined DD+Vol (floor0.3,k5,clip0.5-1.3)",
         "(m*smooth(0.3,5)).clip(0.5,1.3)", dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.3, 5)).clip(0.5, 1.3))),
        ("candidate_floor03", "Floor 0.3 (m*smooth(0.3,5),clip0.5-1.3)",
         "floor sweep 0.3", dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.3, 5)).clip(0.5, 1.3))),
        ("candidate_floor05", "Floor 0.5 (m*smooth(0.5,5),clip0.5-1.3)",
         "floor sweep 0.5", dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.5, 5)).clip(0.5, 1.3))),
        ("candidate_clip_05_12", "Clip 0.5-1.2 (m*smooth(0.6,5))",
         "clip sweep 0.5-1.2", dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 5)).clip(0.5, 1.2))),
        ("candidate_clip_08_10", "Clip 0.8-1.0 (m*smooth(0.6,5))",
         "clip sweep 0.8-1.0", dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 5)).clip(0.8, 1.0))),
        ("candidate_dd_k1", "DD k=1 (m*smooth(0.6,1),clip0.3-1.5)",
         "k-sweep k=1", dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 1)).clip(0.3, 1.5))),
        ("candidate_dd_k5", "DD k=5 (m*smooth(0.6,5),clip0.3-1.5)",
         "k-sweep k=5", dep_overlay((dep_m * drawdown_exposure_smooth(dep_dd, 0.6, 5)).clip(0.3, 1.5))),
    ]
    for sl, nm, ov, e in groupB:
        cands.append(dict(
            slug=sl, name=nm, group="B — deployment-base challenger",
            source="recovered deployment base + overlay", version="-",
            overlay=ov, is_v1=False, has_book=True,
            ret=apply_exposure_to_return(base_ret, e), book=base_book.mul(e, axis=0),
            exposure=e,
        ))

    # ---- Group C: historical low-MDD challengers (return-only, NO book) ----
    groupC = [
        ("candidate_hist_base", "Historical v2 base (raw, no overlay)",
         "none", pd.Series(1.0, index=dates)),
        ("candidate_hist_dd_only", "Historical DD Only (floor0.3,k5)",
         "smooth DD floor0.3 k5 (nb cell 20)", drawdown_exposure_smooth(v2_dd, 0.3, 5)),
        ("candidate_hist_combined", "Historical Combined (floor0.3,k5,clip0.5-1.3)",
         "(m*smooth(0.3,5)).clip(0.5,1.3) (nb cell 22)", (v2_m * drawdown_exposure_smooth(v2_dd, 0.3, 5)).clip(0.5, 1.3)),
        ("candidate_hist_floor03", "Historical Floor 0.3 (clip0.5-1.3)",
         "floor sweep 0.3 (nb cell 15)", (v2_m * drawdown_exposure_smooth(v2_dd, 0.3, 5)).clip(0.5, 1.3)),
        ("candidate_hist_floor05", "Historical Floor 0.5 (clip0.5-1.3)",
         "floor sweep 0.5 (nb cell 15)", (v2_m * drawdown_exposure_smooth(v2_dd, 0.5, 5)).clip(0.5, 1.3)),
        ("candidate_hist_floor06", "Historical Floor 0.6 (clip0.5-1.3)",
         "floor sweep 0.6 (nb cell 15)", (v2_m * drawdown_exposure_smooth(v2_dd, 0.6, 5)).clip(0.5, 1.3)),
    ]
    for sl, nm, ov, e in groupC:
        e = pd.Series(e, index=dates).fillna(1.0)
        cands.append(dict(
            slug=sl, name=nm, group="C — historical low-MDD challenger",
            source="final_returns_v2_with_dates.csv + overlay (robustness nb)",
            version="-", overlay=ov, is_v1=False, has_book=False,
            ret=apply_exposure_to_return(v2, e), book=None, exposure=e,
        ))

    return cands, dates


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------
def evaluate(cand, adv_panel):
    ret = pd.Series(cand["ret"]).astype(float)
    exposure = pd.Series(cand["exposure"]).astype(float)
    eq = (1 + ret).cumprod()
    dd = compute_drawdown(eq)
    has_book = cand["has_book"]
    book = cand["book"]

    # ---- performance + full risk battery (book-independent) ----
    cagr = annualized_return(ret, PPY)
    mdd = max_drawdown(eq)
    ds = drawdown_stats(eq, threshold=DD_THRESHOLD)
    metrics = {
        "Sharpe": float(sharpe_ratio(ret, PPY)),
        "Sortino": float(sortino_ratio(ret, PPY)),
        "CAGR": float(cagr),
        "Volatility": float(annualized_volatility(ret, PPY)),
        "MDD": float(mdd),
        "Calmar": float(cagr / abs(mdd)) if mdd else np.nan,
        "Ulcer": float(ulcer_index(eq)),
        "MaxDD_duration_d": ds["max_dd_duration"],
        "MaxDD_recovery_d": ds["max_dd_recovery"],
        "Longest_underwater_d": ds["longest_underwater"],
        "Time_underwater_frac": ds["time_underwater_frac"],
        "DD_frequency_gt5pct": ds["frequency"],
        "Avg Exposure": float(exposure.mean()),
    }

    # ---- trading / capacity / operational (book-dependent) ----
    artifacts = {"rolling": rolling_metrics(ret, window=PPY, periods_per_year=PPY)}

    if has_book:
        turnover = compute_turnover(book).reindex(ret.index).fillna(0.0)
        tcs = transaction_cost_stress(ret, turnover, TX_COSTS, periods_per_year=PPY)
        cost_adj = float(tcs.loc[tcs["Cost bps"] == COST_ADJ_BPS, "Sharpe"].iloc[0])
        reb = rebalance_analysis(book, REBAL_FREQS)
        cap = capacity_analysis(ret, book, CAPITAL_LEVELS, adv=adv_panel, periods_per_year=PPY)
        ceiling = capacity_ceiling(book, adv_panel, participation_cap=PARTICIPATION_CAP)
        ops = operational_stress_tests(ret, book, equity=eq,
                                       base_cost_bps=COST_ADJ_BPS, periods_per_year=PPY)
        metrics.update({
            "Mean Turnover": float(turnover.mean()),
            "Cost-adj Sharpe (10bps)": cost_adj,
            "Capacity @10% median ($)": float(ceiling["median_capital"]),
            "Capacity @10% p05 ($)": float(ceiling["p05_capital"]),
            "Ops worst Sharpe": float(ops["Sharpe"].min()),
            "Ops Sharpe drop": float(ops["Sharpe"].iloc[0] - ops["Sharpe"].min()),
            "Deployable (has book)": True,
        })
        artifacts.update(turnover=turnover, txcost=tcs, rebalance=reb,
                         capacity=cap, operational=ops)
    else:
        # No position book -> these stages are NOT EVALUABLE. We do compute an
        # overlay-level turnover *lower bound* (|d exposure|) and a tx-cost drag
        # on it, but it understates true book trading and is flagged as a proxy.
        ov_turn = exposure.diff().abs().fillna(0.0)
        tcs_proxy = transaction_cost_stress(ret, ov_turn, TX_COSTS, periods_per_year=PPY)
        cost_adj_proxy = float(tcs_proxy.loc[tcs_proxy["Cost bps"] == COST_ADJ_BPS, "Sharpe"].iloc[0])
        metrics.update({
            "Mean Turnover": np.nan,             # book turnover unknown
            "Cost-adj Sharpe (10bps)": np.nan,   # not comparable (no book turnover)
            "Capacity @10% median ($)": np.nan,
            "Capacity @10% p05 ($)": np.nan,
            "Ops worst Sharpe": np.nan,
            "Ops Sharpe drop": np.nan,
            "Deployable (has book)": False,
            "_overlay_turnover_mean": float(ov_turn.mean()),
            "_cost_adj_sharpe_overlay_proxy_10bps": cost_adj_proxy,
        })
        artifacts.update(txcost_overlay_proxy=tcs_proxy)

    artifacts.update(equity=eq, drawdown=dd, exposure=exposure)
    return metrics, artifacts


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def write_candidate(cand, metrics, art, ghash):
    d = CAND_DIR / cand["slug"]
    d.mkdir(parents=True, exist_ok=True)

    art["equity"].rename("equity").to_csv(d / "equity_curve.csv")
    art["drawdown"].rename("drawdown").to_csv(d / "drawdown_curve.csv")
    art["exposure"].rename("exposure").to_csv(d / "exposure.csv")
    art["rolling"].to_csv(d / "rolling_metrics.csv")
    if cand["has_book"]:
        art["turnover"].rename("turnover").to_csv(d / "turnover.csv")
        art["txcost"].to_csv(d / "txcost_stress.csv", index=False)
        art["rebalance"].to_csv(d / "rebalance.csv", index=False)
        art["capacity"].to_csv(d / "capacity.csv", index=False)
        art["operational"].to_csv(d / "operational_stress.csv", index=False)
    else:
        art["txcost_overlay_proxy"].to_csv(d / "txcost_overlay_proxy.csv", index=False)

    json.dump({k: v for k, v in cand.items()
               if k in ("slug", "name", "group", "source", "version", "overlay",
                        "is_v1", "has_book")},
              open(d / "config.json", "w"), indent=2)
    json.dump({k: (None if (isinstance(v, float) and np.isnan(v)) else v)
               for k, v in metrics.items()},
              open(d / "metrics.json", "w"), indent=2, default=float)
    json.dump({
        "experiment": "exp_006_deployment_candidate_tournament",
        "git_commit": ghash,
        "candidate": cand["name"],
        "group": cand["group"],
        "data_source": cand["source"],
        "overlay_recipe": cand["overlay"],
        "has_position_book": cand["has_book"],
        "book_dependent_stages_evaluable": cand["has_book"],
        "lookahead_safe": "exposure applied via apply_exposure_to_return (shift(1)); "
                          "drawdown uses causal cummax",
    }, open(d / "provenance.json", "w"), indent=2)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def rank(comp):
    """Evidence-based deployment-quality composite.

    Deployability is a *gate*, not a soft penalty: a candidate with no position
    book cannot clear capacity / cost validation, so it can rank within Group C
    on paper quality but is held below every fully-validated book candidate that
    is at least as good. We encode that by sorting Deployable first, then the
    z-scored composite computed over the comparable (book) cohort.
    """
    book = comp[comp["Deployable (has book)"]].copy()

    def z(col, frame, invert=False):
        s = frame[col].astype(float)
        sd = s.std(ddof=0)
        zz = (s - s.mean()) / sd if sd > 0 else s * 0.0
        return -zz if invert else zz

    # composite defined on the book cohort (where every term is populated)
    qual = (1.0 * z("Sharpe", book) + 1.0 * z("Sortino", book)
            + 1.0 * z("Cost-adj Sharpe (10bps)", book) + 1.0 * z("Calmar", book)
            + 1.0 * z("MDD", book) + 0.5 * z("Ulcer", book, invert=True)
            + 0.5 * z("Ops worst Sharpe", book))
    comp["DeployQuality"] = np.nan
    comp.loc[book.index, "DeployQuality"] = qual.values

    # Group-C paper quality: same idea but on risk-adjusted-only terms so the
    # historical rows are still ordered sensibly among themselves.
    nobook = comp[~comp["Deployable (has book)"]].copy()
    if len(nobook):
        paper = (z("Sharpe", nobook) + z("Sortino", nobook)
                 + z("Calmar", nobook) + z("MDD", nobook)
                 + 0.5 * z("Ulcer", nobook, invert=True))
        comp.loc[nobook.index, "PaperQuality"] = paper.values

    comp = comp.sort_values(
        ["Deployable (has book)", "DeployQuality", "MDD", "Sharpe"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    comp.insert(0, "Rank", comp.index + 1)
    return comp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ghash = git_hash()
    cands, dates = build_candidates()

    # real ADV panel for the deployment universe (book candidates only)
    base_ret, base_book, *_ = load_deployment_base()
    tickers = list(base_book.columns)
    close, volume = load_price_volume(
        tickers, data_dir=PROJECT_ROOT / "data/raw/project_04_universe")
    adv = average_daily_volume(daily_dollar_volume(close, volume), window=20)
    adv_panel = adv.reindex(index=dates, columns=tickers).ffill()

    rows = []
    for cand in cands:
        metrics, art = evaluate(cand, adv_panel)
        write_candidate(cand, metrics, art, ghash)
        row = {
            "Candidate": cand["name"], "Group": cand["group"],
            "Source": cand["source"], "Version": cand["version"],
            "Overlay": cand["overlay"], "is_v1": cand["is_v1"],
        }
        row.update(metrics)
        rows.append(row)

    comp = pd.DataFrame(rows)
    comp = rank(comp)

    # column order for the master table
    front = ["Rank", "Candidate", "Group", "Version", "Overlay",
             "Deployable (has book)", "Sharpe", "Sortino", "CAGR", "Volatility",
             "MDD", "Calmar", "Ulcer", "MaxDD_duration_d", "MaxDD_recovery_d",
             "Longest_underwater_d", "Time_underwater_frac", "DD_frequency_gt5pct",
             "Avg Exposure", "Mean Turnover", "Cost-adj Sharpe (10bps)",
             "Capacity @10% median ($)", "Ops worst Sharpe", "Ops Sharpe drop",
             "DeployQuality"]
    cols = [c for c in front if c in comp.columns] + \
           [c for c in comp.columns if c not in front and not c.startswith("_")]
    comp_out = comp[cols]
    comp_out.to_csv(HERE / "master_comparison.csv", index=False)

    json.dump({
        "experiment": "exp_006_deployment_candidate_tournament",
        "git_commit": ghash,
        "n_days": int(len(dates)),
        "date_range": [str(dates[0].date()), str(dates[-1].date())],
        "universe_book_candidates": tickers,
        "groups": {
            "A": "Deployment Candidate V1 (shipped, has book)",
            "B": "deployment-base overlay challengers (have book)",
            "C": "historical v2 low-MDD challengers (return-only, NO book)",
        },
        "battery": {
            "tx_costs_bps": TX_COSTS, "rebalance_freqs": REBAL_FREQS,
            "capital_levels": CAPITAL_LEVELS, "participation_cap": PARTICIPATION_CAP,
            "cost_adj_bps": COST_ADJ_BPS, "dd_threshold": DD_THRESHOLD,
        },
        "roster": [{"slug": c["slug"], "name": c["name"], "group": c["group"],
                    "has_book": c["has_book"]} for c in cands],
        "note": "Book-dependent stages (capacity, book turnover, transaction-cost "
                "stress, rebalance) are NOT EVALUABLE for Group C (no position "
                "book) and are recorded as N/A, treated as a deployment deficiency.",
    }, open(HERE / "tournament_config.json", "w"), indent=2)

    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 40)
    show = comp_out.copy()
    for c in show.columns:
        if show[c].dtype == float:
            show[c] = show[c].round(4)
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
