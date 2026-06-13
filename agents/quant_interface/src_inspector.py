"""
Source inspector — introspects the existing quant-lab src/ library.

Returns structured descriptions of what signals, pipeline parameters, metrics,
and data files are available. The Experiment Designer (Milestone 3) will call
these functions to build valid ExperimentSpec objects from real options.

Nothing here executes any computation or modifies any file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SRC_DIR     = Path(__file__).parent.parent.parent / "src"
DATA_RAW    = Path(__file__).parent.parent.parent / "data" / "raw"
SIGNALS_LIB = SRC_DIR / "signals" / "library.py"
PIPELINE    = SRC_DIR / "pipelines" / "cross_sectional.py"
METRICS_MOD = SRC_DIR / "utils" / "metrics.py"


@dataclass
class SignalDef:
    name: str
    signal_type: str     # momentum / mean_reversion / volatility / composite
    description: str


@dataclass
class PipelineParams:
    valid_signal_types: list[str]
    horizons: list[int]
    long_quantile_range: tuple[float, float]
    short_quantile_range: tuple[float, float]
    notes: str


@dataclass
class DataInventory:
    tickers: list[str]
    data_dir: Path
    file_count: int
    missing: bool = False


@dataclass
class SrcSummary:
    signals: list[SignalDef]
    pipeline: PipelineParams | None
    metric_names: list[str]
    data: DataInventory
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inspect_all() -> SrcSummary:
    """
    Run all inspectors and return a combined SrcSummary.
    Missing or unreadable source files produce warnings, not exceptions.
    """
    warnings: list[str] = []
    signals   = list_available_signals(warnings)
    pipeline  = get_pipeline_params(warnings)
    metrics   = list_metric_names(warnings)
    data      = get_data_inventory(warnings)
    return SrcSummary(
        signals=signals,
        pipeline=pipeline,
        metric_names=metrics,
        data=data,
        warnings=warnings,
    )


def list_available_signals(warnings: list[str] | None = None) -> list[SignalDef]:
    """
    Parse src/signals/library.py and return all named signals.

    Reads the elif chain in get_signal_series() to extract signal names.
    Falls back to an empty list if the file is missing or unparseable.
    """
    w = warnings if warnings is not None else []

    if not SIGNALS_LIB.exists():
        w.append(f"signals/library.py not found at {SIGNALS_LIB}")
        return []

    try:
        source = SIGNALS_LIB.read_text(encoding="utf-8")
        return _parse_signals(source, w)
    except Exception as exc:
        w.append(f"signals/library.py: read error — {exc}")
        return []


def get_pipeline_params(warnings: list[str] | None = None) -> PipelineParams | None:
    """
    Parse src/pipelines/cross_sectional.py and return valid parameters.

    Extracts signal_type options from the if/elif chain and default values
    from the function signature. Falls back to None if unavailable.
    """
    w = warnings if warnings is not None else []

    if not PIPELINE.exists():
        w.append(f"pipelines/cross_sectional.py not found at {PIPELINE}")
        return None

    try:
        source = PIPELINE.read_text(encoding="utf-8")
        return _parse_pipeline(source, w)
    except Exception as exc:
        w.append(f"pipelines/cross_sectional.py: read error — {exc}")
        return None


def list_metric_names(warnings: list[str] | None = None) -> list[str]:
    """
    Parse src/utils/metrics.py and return the names of public metric functions.
    """
    w = warnings if warnings is not None else []

    if not METRICS_MOD.exists():
        w.append(f"utils/metrics.py not found at {METRICS_MOD}")
        return []

    try:
        source = METRICS_MOD.read_text(encoding="utf-8")
        fns = re.findall(r"^def ([a-z][a-z0-9_]*)\(", source, re.MULTILINE)
        return fns
    except Exception as exc:
        w.append(f"utils/metrics.py: read error — {exc}")
        return []


def get_data_inventory(warnings: list[str] | None = None) -> DataInventory:
    """
    Scan data/raw/ for available ticker CSV files.
    """
    w = warnings if warnings is not None else []

    if not DATA_RAW.exists():
        w.append(f"data/raw/ not found at {DATA_RAW}")
        return DataInventory(tickers=[], data_dir=DATA_RAW, file_count=0, missing=True)

    csvs = sorted(DATA_RAW.glob("*.csv"))
    tickers = [f.stem for f in csvs]
    return DataInventory(tickers=tickers, data_dir=DATA_RAW, file_count=len(csvs))


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

# Matches:  signal_name == "mr_ret_5"
#       or: signal_name == 'mom_blend'
_SIGNAL_NAME_RE = re.compile(r'signal_name\s*==\s*["\']([^"\']+)["\']')

# Matches:  elif signal_type == "ret_5_mean_reversion":
_PIPELINE_SIGNAL_RE = re.compile(r'signal_type\s*==\s*["\']([^"\']+)["\']')

# Matches default param values, e.g. horizon: int = 5
_PARAM_DEFAULT_RE = re.compile(
    r'def run_market_alpha_pipeline\(.*?\)',
    re.DOTALL,
)


# Signal name → (type, human description)
_SIGNAL_META: dict[str, tuple[str, str]] = {
    "mr_ret_5":        ("mean_reversion", "5-day mean reversion (short-term reversal)"),
    "mr_ret_10":       ("mean_reversion", "10-day mean reversion"),
    "mr_ret_20":       ("mean_reversion", "20-day mean reversion"),
    "mom_ret_5":       ("momentum",       "5-day momentum"),
    "mom_ret_10":      ("momentum",       "10-day momentum"),
    "mom_ret_20":      ("momentum",       "20-day momentum"),
    "trend_ma_10":     ("momentum",       "10-day MA ratio (trend following)"),
    "trend_ma_20":     ("momentum",       "20-day MA ratio (trend following)"),
    "low_vol_5":       ("volatility",     "5-day low-volatility tilt"),
    "low_vol_20":      ("volatility",     "20-day low-volatility tilt"),
    "mr_blend":        ("composite",      "Equal blend of 5/10/20-day mean reversion"),
    "mom_blend":       ("composite",      "Equal blend of 5/10/20-day momentum"),
    "mr_lowvol_blend": ("composite",      "Blend of mean reversion + low volatility"),
}


def _parse_signals(source: str, warnings: list[str]) -> list[SignalDef]:
    names = _SIGNAL_NAME_RE.findall(source)
    if not names:
        warnings.append("signals/library.py: no signal names found via regex")
        return []

    signals = []
    for name in names:
        meta = _SIGNAL_META.get(name)
        if meta:
            sig_type, desc = meta
        else:
            sig_type = "unknown"
            desc = f"Signal '{name}' (type not classified)"
            warnings.append(f"signals/library.py: unclassified signal '{name}'")
        signals.append(SignalDef(name=name, signal_type=sig_type, description=desc))

    return signals


def _parse_pipeline(source: str, warnings: list[str]) -> PipelineParams:
    signal_types = _PIPELINE_SIGNAL_RE.findall(source)
    if not signal_types:
        warnings.append("cross_sectional.py: no signal_type options found via regex")

    # Extract defaults from function signature
    sig_match = _PARAM_DEFAULT_RE.search(source)
    horizon_default = 5
    long_q_default  = 0.8
    short_q_default = 0.2

    if sig_match:
        sig_text = sig_match.group(0)
        h = re.search(r'horizon\s*:\s*int\s*=\s*(\d+)', sig_text)
        lq = re.search(r'long_quantile\s*:\s*float\s*=\s*([\d.]+)', sig_text)
        sq = re.search(r'short_quantile\s*:\s*float\s*=\s*([\d.]+)', sig_text)
        if h:
            horizon_default = int(h.group(1))
        if lq:
            long_q_default = float(lq.group(1))
        if sq:
            short_q_default = float(sq.group(1))

    return PipelineParams(
        valid_signal_types=signal_types,
        horizons=[1, 5, 10, 20],        # standard horizons used in the project
        long_quantile_range=(0.7, 0.9),
        short_quantile_range=(0.1, 0.3),
        notes=(
            f"Default horizon={horizon_default}d, "
            f"long_quantile={long_q_default}, "
            f"short_quantile={short_q_default}. "
            "Pipeline: build_market_panel → add_price_features → "
            "add_forward_returns → signal → rank → long/short weights."
        ),
    )
