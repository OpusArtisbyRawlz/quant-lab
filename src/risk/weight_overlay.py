"""
weight_overlay.py — per-child weight-level exposure overlays.

Some historical strategy variants scale their cross-sectional book by a time-varying
*exposure* at the weight level (before returns are formed). This differs from the
return-level drawdown/vol overlays (``src/risk/drawdown``, ``src/risk/vol_target``),
which post-process the portfolio return series.

Project 04's volatility-regime variants all follow one family (notebook cells 40/149-183):
an exposure derived from Project 02's *recovered* ``p_high_vol_calibrated`` (p), lagged
one day, applied to the LS book, optionally partial / renormalised / neutralised:

    x            = 1 - p
    transform    = x (linear) | sqrt(x) | x**alpha (pow)
    f            = (0.5 + 0.5*transform) if partial else transform
    weight      *= f.shift(1)
    if normalize:  weight /= gross_per_date            # renormalise gross to 1.0
    if neutralize: weight -= per-date mean; weight /= gross_per_date   # dollar-neutral

Reuses the recovered P02 artifact verbatim; invents nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
_P02_OOF = (_REPO_ROOT / "research" / "project_02_volatility_regime"
            / "artifacts" / "vol_regime_calibrated_oof.csv")


def _regime_multiplier(transform: str, alpha: float, partial: bool) -> pd.DataFrame:
    """Per-date exposure multiplier (lag-1) from the P02 OOF artifact.
    Returns [Date, _wov_mult]; dates outside OOF coverage are NaN (historical merge
    left-joins, preserving that behaviour)."""
    oof = pd.read_csv(_P02_OOF, parse_dates=["Date"])
    oof["Date"] = oof["Date"].dt.normalize()
    x = 1.0 - oof["p_high_vol_calibrated"]
    if transform == "linear":
        t = x
    elif transform == "sqrt":
        t = np.sqrt(x)
    elif transform == "pow":
        t = x ** float(alpha)
    else:
        raise ValueError(f"Unknown weight_overlay transform: {transform!r}")
    f = (0.5 + 0.5 * t) if partial else t
    return pd.DataFrame({"Date": oof["Date"], "_wov_mult": f.shift(1)})


def _renorm(out: pd.DataFrame) -> pd.DataFrame:
    gross = out.groupby(out["Date"])["weight"].transform(lambda s: s.abs().sum())
    out["weight"] = out["weight"] / gross
    return out


def apply_weight_overlay(panel: pd.DataFrame, overlay: dict[str, Any]) -> pd.DataFrame:
    """Scale ``panel['weight']`` by a P02 vol-regime exposure, per the overlay spec.
    Returns a new panel; ``panel`` is not mutated.

    overlay methods:
      * ``vol_regime`` — general: {transform, alpha, partial, normalize, neutralize}
      * ``vol_regime_partial`` — alias for {transform: sqrt, partial: true, normalize: true}
    """
    method = (overlay or {}).get("method")
    if method == "vol_regime_partial":
        transform, alpha, partial, normalize, neutralize = "sqrt", 0.7, True, True, False
    elif method == "vol_regime":
        transform = overlay.get("transform", "sqrt")
        alpha = float(overlay.get("alpha", 0.7))
        partial = bool(overlay.get("partial", False))
        normalize = bool(overlay.get("normalize", False))
        neutralize = bool(overlay.get("neutralize", False))
    else:
        raise ValueError(f"Unknown weight_overlay method: {method!r}")

    out = panel.copy()
    date_norm = pd.to_datetime(out["Date"]).dt.normalize()
    mult = _regime_multiplier(transform, alpha, partial)
    merged = pd.DataFrame({"Date": date_norm}).merge(mult, on="Date", how="left")["_wov_mult"]
    out["weight"] = out["weight"].to_numpy() * merged.to_numpy()
    if normalize or neutralize:
        out = _renorm(out)
    if neutralize:
        # subtract per-date mean (dollar-neutral), then renormalise gross to 1.0
        out["weight"] = out["weight"] - out.groupby(out["Date"])["weight"].transform("mean")
        out = _renorm(out)
    return out
