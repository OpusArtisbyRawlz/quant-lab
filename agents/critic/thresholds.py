"""
CriticThresholds — loads conservative defaults from critic_defaults.toml and
merges per-experiment overrides from ExperimentSpec.success_criteria.

Resolution order (highest priority wins):
  ExperimentSpec.success_criteria  →  critic_defaults.toml

Callers never hard-code threshold values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "critic_defaults.toml"

# Maps success_criteria dict keys → CriticThresholds attribute names.
# "mdd" in success_criteria means "the mdd threshold" (maximum_mdd in config).
_CRITERIA_KEY_MAP: dict[str, str] = {
    "sharpe": "minimum_sharpe",
    "mdd":    "maximum_mdd",
    "calmar": "minimum_calmar",
    "cagr":   "minimum_cagr",
}


@dataclass
class CriticThresholds:
    """
    Resolved thresholds for a single Critic evaluation.

    Each threshold is either a float (active) or None (skipped — metric not
    checked in the pass/fail decision).

    ``sources`` records where each threshold came from: "spec", "config", or
    "none" (absent from both).  This is included in CritiqueResult.thresholds_used
    so the log is self-explanatory.
    """
    minimum_sharpe:  float | None = None
    maximum_mdd:     float | None = None   # mdd must be >= this (e.g. >= -0.40)
    minimum_calmar:  float | None = None
    minimum_cagr:    float | None = None
    policy:          str          = "strict"
    max_retest_attempts: int      = 1
    metric_basis:    str          = "net"   # "net" (default) | "gross"
    downgrade_on_robustness_flags: bool = True
    sources: dict[str, str]       = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def load_defaults(cls, config_path: Path | None = None) -> "CriticThresholds":
        """
        Read thresholds from a TOML file.

        Falls back to zero-threshold behaviour (all None) if tomllib/tomli is
        unavailable — callers should treat that as a warning, not a hard error.
        """
        path = config_path or _DEFAULT_CONFIG
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            try:
                import tomli as tomllib  # backport
            except ImportError:
                log.warning(
                    "tomllib/tomli not available — critic thresholds not loaded from %s. "
                    "Install tomli or use Python 3.11+.",
                    path,
                )
                return cls(sources={k: "none" for k in _CRITERIA_KEY_MAP.values()})

        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except FileNotFoundError:
            log.warning("critic_defaults.toml not found at %s — using empty thresholds.", path)
            return cls(sources={k: "none" for k in _CRITERIA_KEY_MAP.values()})

        thresholds = data.get("thresholds", {})
        policy_cfg = data.get("decision_policy", {})
        eval_cfg   = data.get("evaluation", {})

        sources: dict[str, str] = {}

        def _get(key: str) -> float | None:
            val = thresholds.get(key)
            sources[key] = "config" if val is not None else "none"
            return float(val) if val is not None else None

        return cls(
            minimum_sharpe      = _get("minimum_sharpe"),
            maximum_mdd         = _get("maximum_mdd"),
            minimum_calmar      = _get("minimum_calmar"),
            minimum_cagr        = _get("minimum_cagr"),
            policy              = policy_cfg.get("policy", "strict"),
            max_retest_attempts = int(policy_cfg.get("max_retest_attempts", 1)),
            metric_basis        = eval_cfg.get("metric_basis", "net"),
            downgrade_on_robustness_flags = bool(
                eval_cfg.get("downgrade_on_robustness_flags", True)
            ),
            sources             = sources,
        )

    def merge(self, success_criteria: dict[str, Any]) -> "CriticThresholds":
        """
        Return a new CriticThresholds with spec-level overrides applied.

        Recognised success_criteria keys: sharpe, mdd, calmar, cagr.
        Unrecognised keys are logged as warnings and ignored.
        """
        import copy
        merged = copy.copy(self)
        merged.sources = dict(self.sources)  # shallow copy of sources dict

        for crit_key, val in success_criteria.items():
            attr = _CRITERIA_KEY_MAP.get(crit_key)
            if attr is None:
                log.warning(
                    "success_criteria key %r not recognised by Critic — ignored. "
                    "Recognised keys: %s",
                    crit_key, list(_CRITERIA_KEY_MAP.keys()),
                )
                continue
            setattr(merged, attr, float(val))
            merged.sources[attr] = "spec"

        return merged

    # ------------------------------------------------------------------ #
    # Serialisation (for logging)                                          #
    # ------------------------------------------------------------------ #

    def as_log_dict(self) -> dict[str, Any]:
        """
        Return a dict suitable for embedding in CritiqueResult.thresholds_used.

        Format: {metric_attr: {"value": v, "source": "spec"|"config"|"none"}}
        """
        attrs = ("minimum_sharpe", "maximum_mdd", "minimum_calmar", "minimum_cagr")
        out: dict[str, Any] = {
            attr: {
                "value":  getattr(self, attr),
                "source": self.sources.get(attr, "none"),
            }
            for attr in attrs
        }
        out["metric_basis"] = self.metric_basis
        return out
