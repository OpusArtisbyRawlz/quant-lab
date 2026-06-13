"""
Artifact reader — reads a single experiment folder into a typed ArtifactBundle.

Design principle: resilient over complete.
Every file is attempted independently. A missing or malformed file produces a
warning in the bundle's `warnings` list and leaves the corresponding field as
None or an empty collection. A partially-read bundle is always returned — the
caller decides what to do with incomplete data.

Experiment type taxonomy
------------------------
Type is inferred from the keys present in metrics.json. It is always a best-
guess — human or agent review may correct it later. Recognised types:

  classification  metrics contain: auc / accuracy / precision / recall / f1
  regression      metrics contain: mse / mae / rmse / r2 / r_squared
  risk_overlay    metrics contain: calmar / avg_exposure / mdd_reduction
                  OR config contains "drawdown" in model name
  portfolio       metrics contain: sharpe / cagr / vol — or strategy_comparison.csv
                  is present (default for cross-sectional long/short experiments)
  unknown         none of the above signals are present

File priority per experiment folder:
  metrics.json            → raw model/performance metrics dict
  config.json / config.yaml → experiment configuration dict
  results_summary.md      → free-text summary (also accepts result_summary.md)
  notes.md                → researcher notes
  strategy_comparison.csv → multiple strategy rows (Sharpe, MDD, CAGR, Vol, Calmar, ...)
  final_*_summary.csv     → alternative summary CSV (project 05 pattern)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Alternative filenames tried in order for each slot
_SUMMARY_NAMES = ["results_summary.md", "result_summary.md", "project_summary.md"]
_NOTES_NAMES   = ["notes.md"]
_CONFIG_NAMES  = ["config.json", "config.yaml"]
_METRICS_NAMES = ["metrics.json"]
_STRATEGY_COMPARISON_NAMES = ["strategy_comparison.csv"]
_FINAL_SUMMARY_NAMES = [
    "final_project05_summary.csv",
    "final_project04_summary.csv",
    "final_summary.csv",
]


@dataclass
class StrategyVariant:
    """One row from a strategy_comparison CSV or final summary CSV."""
    strategy_name: str
    sharpe: float | None = None
    mdd: float | None = None
    cagr: float | None = None
    vol: float | None = None
    calmar: float | None = None
    avg_exposure: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Experiment type detection — key signatures per type
# ---------------------------------------------------------------------------

_CLASSIFICATION_KEYS = {"auc", "accuracy", "precision", "recall", "f1", "f1_score",
                         "roc_auc", "log_loss"}
_REGRESSION_KEYS     = {"mse", "mae", "rmse", "r2", "r_squared", "mean_squared_error",
                         "mean_absolute_error"}
_RISK_OVERLAY_KEYS   = {"avg_exposure", "mdd_reduction", "exposure"}
_PORTFOLIO_KEYS      = {"sharpe", "cagr", "vol", "volatility"}


def detect_experiment_type(
    metrics: dict[str, Any] | None,
    config: dict[str, Any] | None,
    has_strategy_variants: bool,
) -> str:
    """
    Infer experiment type from available evidence. Returns one of:
      classification / regression / risk_overlay / portfolio / unknown

    Priority order:
      1. Config-based hint (explicit model name) — highest confidence
      2. Classification/regression metric keys — unambiguous domain signals
      3. Risk overlay metric keys (avg_exposure, mdd_reduction, exposure)
      4. Portfolio metric keys (sharpe, cagr, vol, volatility)
      5. Strategy variants present → portfolio
      6. Unknown
    """
    # Config hint takes priority: "drawdown"/"exposure"/"overlay" in model name
    if config:
        model = str(config.get("model", "") or config.get("final_model", "")).lower()
        if "drawdown" in model or "exposure" in model or "overlay" in model:
            return "risk_overlay"

    if metrics:
        keys = {k.lower() for k in metrics}
        if keys & _CLASSIFICATION_KEYS:
            return "classification"
        if keys & _REGRESSION_KEYS:
            return "regression"
        if keys & _RISK_OVERLAY_KEYS:
            return "risk_overlay"
        if keys & _PORTFOLIO_KEYS:
            return "portfolio"

    # Strategy comparison CSV present → portfolio experiment
    if has_strategy_variants:
        return "portfolio"

    return "unknown"


@dataclass
class ArtifactBundle:
    """
    All parseable content from one experiment folder.

    Every field is optional. Callers must check for None / empty list before
    using a field rather than assuming presence.
    """
    experiment_id: str
    artifact_path: Path

    # Parsed content — all optional
    metrics: dict[str, Any] | None = None          # from metrics.json (raw, unmodified)
    config: dict[str, Any] | None = None           # from config.json / config.yaml
    summary_text: str | None = None                # from *_summary.md
    notes_text: str | None = None                  # from notes.md
    strategy_variants: list[StrategyVariant] = field(default_factory=list)

    # Inferred after all files are read
    experiment_type: str | None = None             # classification/regression/portfolio/risk_overlay/unknown

    # Audit
    files_found: list[str] = field(default_factory=list)
    files_missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return (
            self.metrics is None
            and self.config is None
            and self.summary_text is None
            and not self.strategy_variants
        )

    def best_sharpe(self) -> float | None:
        """Return the highest Sharpe from strategy_variants, or metrics if no variants."""
        if self.strategy_variants:
            sharpes = [v.sharpe for v in self.strategy_variants if v.sharpe is not None]
            return max(sharpes) if sharpes else None
        if self.metrics:
            return self.metrics.get("sharpe") or self.metrics.get("Sharpe")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_experiment_artifact(exp_dir: Path) -> ArtifactBundle:
    """
    Read all recognisable files in an experiment folder.

    Always returns an ArtifactBundle. Never raises — errors are captured in
    bundle.warnings.
    """
    exp_id = exp_dir.name
    bundle = ArtifactBundle(experiment_id=exp_id, artifact_path=exp_dir)

    bundle.metrics           = _try_read_metrics(exp_dir, bundle)
    bundle.config            = _try_read_config(exp_dir, bundle)
    bundle.summary_text      = _try_read_text(exp_dir, _SUMMARY_NAMES, "summary", bundle)
    bundle.notes_text        = _try_read_text(exp_dir, _NOTES_NAMES, "notes", bundle)
    bundle.strategy_variants = _try_read_strategy_variants(exp_dir, bundle)

    # Type detection runs after all files are loaded so it can use all evidence
    bundle.experiment_type = detect_experiment_type(
        metrics=bundle.metrics,
        config=bundle.config,
        has_strategy_variants=bool(bundle.strategy_variants),
    )

    return bundle


# ---------------------------------------------------------------------------
# Per-file readers — each returns None / [] on any failure
# ---------------------------------------------------------------------------

def _try_read_metrics(exp_dir: Path, bundle: ArtifactBundle) -> dict[str, Any] | None:
    for name in _METRICS_NAMES:
        path = exp_dir / name
        if not path.exists():
            continue
        bundle.files_found.append(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                bundle.warnings.append(f"{name}: expected JSON object, got {type(data).__name__}")
                return None
            return data
        except Exception as exc:
            bundle.warnings.append(f"{name}: parse error — {exc}")
            return None
    bundle.files_missing.append("metrics.json")
    return None


def _try_read_config(exp_dir: Path, bundle: ArtifactBundle) -> dict[str, Any] | None:
    for name in _CONFIG_NAMES:
        path = exp_dir / name
        if not path.exists():
            continue
        bundle.files_found.append(name)
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                bundle.warnings.append(f"{name}: file is empty")
                return None
            if name.endswith(".json"):
                data = json.loads(text)
            else:
                # yaml — attempt import, fall back to raw text dict
                data = _parse_yaml_safe(text, name, bundle)
            if data is None:
                return None
            if not isinstance(data, dict):
                bundle.warnings.append(f"{name}: expected mapping, got {type(data).__name__}")
                return None
            return data
        except Exception as exc:
            bundle.warnings.append(f"{name}: parse error — {exc}")
            return None
    bundle.files_missing.append("config.json/yaml")
    return None


def _try_read_text(
    exp_dir: Path,
    candidates: list[str],
    slot_name: str,
    bundle: ArtifactBundle,
) -> str | None:
    for name in candidates:
        path = exp_dir / name
        if not path.exists():
            continue
        bundle.files_found.append(name)
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                bundle.warnings.append(f"{name}: file is empty")
                return None
            return text
        except Exception as exc:
            bundle.warnings.append(f"{name}: read error — {exc}")
            return None
    bundle.files_missing.append(slot_name)
    return None


def _try_read_strategy_variants(
    exp_dir: Path,
    bundle: ArtifactBundle,
) -> list[StrategyVariant]:
    """
    Try strategy_comparison.csv first, then final_*_summary.csv.
    Returns an empty list if neither exists or both fail.
    """
    for name in _STRATEGY_COMPARISON_NAMES + _FINAL_SUMMARY_NAMES:
        path = exp_dir / name
        if not path.exists():
            continue
        bundle.files_found.append(name)
        try:
            variants = _parse_strategy_csv(path, bundle)
            if variants:
                return variants
        except Exception as exc:
            bundle.warnings.append(f"{name}: parse error — {exc}")
    bundle.files_missing.append("strategy_comparison.csv")
    return []


def _parse_strategy_csv(
    path: Path,
    bundle: ArtifactBundle,
) -> list[StrategyVariant]:
    """
    Parse a strategy comparison CSV into StrategyVariant objects.

    Expects a header row. The first column is treated as the strategy name
    regardless of its label. All numeric columns are parsed tolerantly.
    Unknown columns go into StrategyVariant.extra.
    """
    import csv as _csv

    _KNOWN = {
        "sharpe":       ("sharpe",       float),
        "mdd":          ("mdd",          float),
        "cagr":         ("cagr",         float),
        "vol":          ("vol",          float),
        "calmar":       ("calmar",       float),
        "avg_exposure": ("avg_exposure", float),
    }

    variants: list[StrategyVariant] = []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        bundle.warnings.append(f"{path.name}: file is empty")
        return []

    reader = _csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        bundle.warnings.append(f"{path.name}: no header row found")
        return []

    name_col = reader.fieldnames[0]  # first column = strategy name

    for row_num, row in enumerate(reader, start=2):
        strategy_name = (row.get(name_col) or "").strip()
        if not strategy_name:
            bundle.warnings.append(f"{path.name} row {row_num}: empty strategy name, skipped")
            continue

        v = StrategyVariant(strategy_name=strategy_name)
        for col, raw_val in row.items():
            if col == name_col:
                continue
            key = col.strip().lower().replace(" ", "_")
            if key in _KNOWN:
                attr, typ = _KNOWN[key]
                setattr(v, attr, _safe_float(raw_val, f"{path.name}:{col}", bundle))
            else:
                parsed = _safe_float(raw_val, None, None)
                v.extra[col] = parsed if parsed is not None else raw_val

        variants.append(v)

    return variants


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(
    val: str | None,
    label: str | None,
    bundle: ArtifactBundle | None,
) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        if label and bundle is not None:
            bundle.warnings.append(f"{label}: could not parse '{val}' as float")
        return None


def _parse_yaml_safe(
    text: str,
    name: str,
    bundle: ArtifactBundle,
) -> dict[str, Any] | None:
    """Attempt PyYAML parse; fall back gracefully if not installed."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        bundle.warnings.append(
            f"{name}: PyYAML not installed — config.yaml cannot be parsed. "
            "Install pyyaml or use config.json instead."
        )
        return None
    except Exception as exc:
        bundle.warnings.append(f"{name}: YAML parse error — {exc}")
        return None
