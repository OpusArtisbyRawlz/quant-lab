"""
weight_overlay.py — per-child weight-level exposure overlays.

Some historical strategy variants scale their cross-sectional book by a time-varying
*exposure* at the weight level (before returns are formed), then renormalise gross to
1.0 per date. This differs from the return-level drawdown overlay (``src/risk/drawdown``),
which post-processes the portfolio return series.

The only historical instance is Project 04's ``ls_20pct_plus_sqrt_partial_normalized``,
whose exposure is derived from Project 02's *recovered* volatility-regime output
``p_high_vol_calibrated``:

    exp_sqrt    = sqrt(1 - p_high_vol_calibrated)          # P04 notebook cell 40
    multiplier  = a + b * exp_sqrt.shift(1)                # a=0.5, b=0.5 (partial), lag-1
    weight     *= multiplier ; renormalise gross to 1.0 per date   # cells 167/172

This reuses the recovered P02 artifact verbatim; it invents nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
_P02_OOF = (_REPO_ROOT / "research" / "project_02_volatility_regime"
            / "artifacts" / "vol_regime_calibrated_oof.csv")


def _vol_regime_partial_exposure(a: float, b: float) -> pd.DataFrame:
    """Per-date multiplier (a + b·sqrt(1-p_high_vol), lag-1) from the P02 OOF artifact.
    Returns a frame [Date, _wov_mult]; dates outside the OOF coverage are NaN (the
    historical merge left-joins, so those dates carry the same NaN behaviour)."""
    oof = pd.read_csv(_P02_OOF, parse_dates=["Date"])
    oof["Date"] = oof["Date"].dt.normalize()
    exp_sqrt = np.sqrt(1.0 - oof["p_high_vol_calibrated"]).shift(1)
    return pd.DataFrame({"Date": oof["Date"], "_wov_mult": a + b * exp_sqrt})


def apply_weight_overlay(panel: pd.DataFrame, overlay: dict[str, Any]) -> pd.DataFrame:
    """Scale ``panel['weight']`` by a per-date exposure multiplier, then renormalise
    gross to 1.0 per date. Returns a new panel; ``panel`` is not mutated.

    overlay = {"method": "vol_regime_partial", "a": 0.5, "b": 0.5}
    """
    method = (overlay or {}).get("method")
    if method != "vol_regime_partial":
        raise ValueError(f"Unknown weight_overlay method: {method!r}")
    a = float(overlay.get("a", 0.5))
    b = float(overlay.get("b", 0.5))
    out = panel.copy()
    date_norm = pd.to_datetime(out["Date"]).dt.normalize()
    mult = _vol_regime_partial_exposure(a, b)
    merged = pd.DataFrame({"Date": date_norm}).merge(mult, on="Date", how="left")["_wov_mult"]
    out["weight"] = out["weight"].to_numpy() * merged.to_numpy()
    gross = out.groupby(out["Date"])["weight"].transform(lambda x: x.abs().sum())
    out["weight"] = out["weight"] / gross
    return out
