"""
deployment_stage.py — reusable deployment-evaluation stage.

Runs AFTER experiment execution and BEFORE the Project 07 hand-off. Given a composite
``PortfolioSpec`` experiment, it composes the deployment base *position book* (the book
projection of the same composition the return pipeline uses — no new strategy logic),
then runs the deployment battery + tournament (``src/analysis/deployment_tournament``,
which reuses the existing ``src/analysis`` modules). General: any book-bearing evaluated
object can be deployment-evaluated; Project 06 is just the first caller.

The base is composed from the *recovered* P05 PortfolioSpec, not a stored CSV, so the
deployment base is self-consistent. See docs on the historical ``portfolio_dd_exposure``
data-integrity note.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.pipelines.cross_sectional import run_market_alpha_pipeline
from src.signals.combine import apply_signal_combo
from src.risk import drawdown as dd
from src.risk.weight_overlay import apply_weight_overlay
from src.portfolio.composite import PortfolioSpec
import src.analysis.deployment_tournament as dt


def _pivot(panel: pd.DataFrame, col: str) -> pd.DataFrame:
    p = panel.copy()
    p["Date"] = pd.to_datetime(p["Date"]).dt.normalize()
    return p.pivot_table(index="Date", columns="ticker", values=col).sort_index()


def _book_return(book: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    f = fwd.reindex(index=book.index, columns=book.columns)
    return (book * f).sum(axis=1)


def _apply_book_overlay(book: pd.DataFrame, overlay: dict, fwd: pd.DataFrame) -> pd.DataFrame:
    """Book projection of a return-level smooth-DD overlay: scale the book by the
    (lagged) drawdown exposure derived from the book's own return — identical to
    ``apply_exposure_to_return`` at the return level."""
    method = (overlay or {}).get("method")
    if method not in ("smooth_dd", "smooth_drawdown_exposure"):
        raise ValueError(f"Unsupported book overlay: {method!r}")
    ret = _book_return(book, fwd)
    exp = dd.drawdown_exposure_smooth(
        dd.compute_drawdown((1 + ret).cumprod()),
        floor=float(overlay.get("floor", 0.55)), k=float(overlay.get("k", 5)))
    return book.mul(exp.shift(1).fillna(1.0), axis=0)


def _child_book(child: dict, base_panel: pd.DataFrame, fwd: pd.DataFrame) -> pd.DataFrame:
    """Book stream for one child (mirrors runner._child_return_stream at book level)."""
    nested = child.get("portfolio")
    if nested:
        parts = [
            _child_book(c, base_panel, fwd) * float(c["weight"])
            for c in sorted(nested["children"], key=lambda x: x["child_id"])
        ]
        book = parts[0]
        for p in parts[1:]:
            book = book.add(p, fill_value=0.0)
        if nested.get("overlay"):
            book = _apply_book_overlay(book, nested["overlay"], fwd)
    else:
        panel = apply_signal_combo(base_panel, signal_names=child["features"])
        if child.get("weight_overlay"):
            panel = apply_weight_overlay(panel, child["weight_overlay"])
        book = _pivot(panel, "weight")
    if child.get("overlay"):
        book = _apply_book_overlay(book, child["overlay"], fwd)
    return book


def compose_deployment_base(pf: dict, data_dict) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    """Compose the V1 deployment base (return, book, portfolio exposure) from a
    PortfolioSpec — the self-consistent recovered base. Returns (v1_ret, v1_book,
    portfolio_exposure)."""
    base_panel = run_market_alpha_pipeline(data_dict)
    fwd = _pivot(base_panel, "fwd_ret_5")
    children = sorted(pf["children"], key=lambda c: c["child_id"])
    combined = None
    for c in children:
        part = _child_book(c, base_panel, fwd) * float(c["weight"])
        combined = part if combined is None else combined.add(part, fill_value=0.0)
    base_book = combined
    base_ret = _book_return(base_book, fwd)
    # portfolio-level overlay exposure (unshifted) — the authoritative portfolio_dd_exposure
    raw_exp = dd.drawdown_exposure_smooth(
        dd.compute_drawdown((1 + base_ret).cumprod()),
        floor=float((pf.get("overlay") or {}).get("floor", 0.55)),
        k=float((pf.get("overlay") or {}).get("k", 5)))
    v1_book = base_book.mul(raw_exp.shift(1).fillna(1.0), axis=0)
    v1_ret = _book_return(v1_book, fwd)
    return v1_ret, v1_book, raw_exp


def run_deployment_tournament(
    pf: dict, data_dict, *, v2_source: Path, adv_data_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compose the recovered P05 base and run the Project-06 deployment tournament.

    Returns (master_comparison_frame, decision). ``decision`` records the promoted
    candidate (rank 1 deployable) — the deployment decision handed to Project 07.
    """
    v1_ret, v1_book, raw_exp = compose_deployment_base(pf, data_dict)
    v2 = pd.read_csv(v2_source)
    v2["date"] = pd.to_datetime(v2["date"])
    v2 = v2.set_index("date")["returns"].astype(float)
    v2.index = v1_book.index  # align to deployment dates (driver asserts equality)
    adv = dt.build_adv_panel(list(v1_book.columns), v1_book.index, adv_data_dir)
    comp = dt.run_tournament(v1_ret, v1_book, raw_exp, v2, adv)
    top = comp.iloc[0]
    decision = {
        "promoted_candidate": top["Candidate"],
        "promoted_deploy_quality": float(top["DeployQuality"]),
        "incumbent_v1_sharpe": float(comp.loc[comp["is_v1"], "Sharpe"].iloc[0]),
        "n_candidates": int(len(comp)),
        "n_deployable": int(comp["Deployable (has book)"].sum()),
    }
    return comp, decision
